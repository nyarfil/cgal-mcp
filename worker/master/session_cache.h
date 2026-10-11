#pragma once
// Persistent-worker (--serve) cache of parsed meshes and built AABB trees.
//
// Disabled unless CGAL_MASTER_SESSION_CACHE_MB > 0 is set in the worker environment, which the
// parent supervisor does only for persistent workers with the explicit opt-in flag; the one-shot
// path never enables it. Entries are immutable after construction (consumers receive
// shared_ptr<const T> and only call const queries), keyed by the VERIFIED content hash plus
// operation kind, kernel/traits identity, declared type/format/unit and the CGAL version, and are
// bounded by an LRU with both an entry count and a byte budget. A hit still re-reads and re-hashes
// the artifact file, so a tampered or replaced file can never be served from the cache.
#include "artifact_io.h"
#include "protocol.h"

#include <CGAL/version.h>

#define CGAL_MASTER_CACHE_STR_DETAIL(value) #value
#define CGAL_MASTER_CACHE_STR(value) CGAL_MASTER_CACHE_STR_DETAIL(value)

#include <cstddef>
#include <cstdlib>
#include <list>
#include <memory>
#include <new>
#include <string>
#include <unordered_map>
#include <utility>

namespace cgal_master {

struct SessionCacheEntry {
  virtual ~SessionCacheEntry() = default;
  std::size_t bytes = 0;  // conservative estimate used for the memory budget
};

class SessionCache {
 public:
  static SessionCache& instance() {
    static SessionCache cache;
    return cache;
  }

  void configure(std::size_t budget_bytes, std::size_t max_entries) {
    clear();
    budget_ = budget_bytes;
    max_entries_ = max_entries == 0 ? 1 : max_entries;
  }
  void configure_from_environment() {
    const char* mb = std::getenv("CGAL_MASTER_SESSION_CACHE_MB");
    const char* entries = std::getenv("CGAL_MASTER_SESSION_CACHE_ENTRIES");
    const long long budget_mb = mb ? std::atoll(mb) : 0;
    const long long count = entries ? std::atoll(entries) : 8;
    configure(budget_mb > 0 ? static_cast<std::size_t>(budget_mb) * 1024 * 1024 : 0,
              count > 0 ? static_cast<std::size_t>(count) : 8);
  }
  bool enabled() const { return budget_ > 0; }
  void begin_request() { request_ = Counters{}; }

  static std::string key(const std::string& kind, const std::string& traits,
                         const ArtifactInput& input) {
    return kind + "|" + traits + "|CGAL " + CGAL_MASTER_CACHE_STR(CGAL_VERSION) + "|" + input.type + "|" +
           input.format + "|" + input.unit + "|" + input.sha256;
  }

  // Cache lookup. On a hit the artifact is re-read and re-hashed (throws exactly like the cold
  // path when the file does not match the declared hash). Counts a miss when enabled and absent.
  template <class T>
  std::shared_ptr<const T> find(const std::string& k, const ArtifactInput& input) {
    if (!enabled()) return nullptr;
    const auto found = index_.find(k);
    if (found == index_.end()) {
      ++request_.misses;
      ++total_.misses;
      return nullptr;
    }
    (void)read_verified_input_bytes(input);
    order_.splice(order_.begin(), order_, found->second);
    ++request_.hits;
    ++total_.hits;
    return std::static_pointer_cast<const T>(found->second->entry);
  }

  // Build an entry (always) and insert it when enabled. A bad_alloc while building first drops the
  // whole cache and retries once; a second failure propagates (the host then reports MEMORY_LIMIT
  // and retires the process).
  template <class T, class Build>
  std::shared_ptr<const T> build(const std::string& k, Build&& builder) {
    std::shared_ptr<T> entry;
    try {
      entry = builder();
    } catch (const std::bad_alloc&) {
      if (!enabled() || index_.empty()) throw;
      ++request_.pressure_evictions;
      ++total_.pressure_evictions;
      clear();
      entry = builder();
    }
    if (enabled()) insert(k, entry);
    return entry;
  }

  Json request_stats() const {
    return Json{{"enabled", enabled()},
                {"hits", request_.hits},
                {"misses", request_.misses},
                {"stored", request_.stored},
                {"evictions", request_.evictions},
                {"pressure_evictions", request_.pressure_evictions},
                {"oversize_skipped", request_.oversize},
                {"entries", index_.size()},
                {"bytes", bytes_},
                {"budget_bytes", budget_},
                {"max_entries", max_entries_},
                {"total_hits", total_.hits},
                {"total_misses", total_.misses}};
  }

  void clear() {
    order_.clear();
    index_.clear();
    bytes_ = 0;
  }

 private:
  struct Node {
    std::string key;
    std::shared_ptr<SessionCacheEntry> entry;
  };
  struct Counters {
    std::size_t hits = 0, misses = 0, stored = 0, evictions = 0, pressure_evictions = 0,
                oversize = 0;
  };

  void insert(const std::string& k, const std::shared_ptr<SessionCacheEntry>& entry) {
    if (entry->bytes > budget_) {
      ++request_.oversize;
      return;
    }
    while (!order_.empty() && (bytes_ + entry->bytes > budget_ || order_.size() >= max_entries_)) {
      bytes_ -= order_.back().entry->bytes;
      index_.erase(order_.back().key);
      order_.pop_back();
      ++request_.evictions;
      ++total_.evictions;
    }
    order_.push_front(Node{k, entry});
    index_[k] = order_.begin();
    bytes_ += entry->bytes;
    ++request_.stored;
  }

  std::size_t budget_ = 0;
  std::size_t max_entries_ = 8;
  std::size_t bytes_ = 0;
  std::list<Node> order_;
  std::unordered_map<std::string, std::list<Node>::iterator> index_;
  Counters request_;
  Counters total_;
};

}  // namespace cgal_master

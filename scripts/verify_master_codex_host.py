"""Call installed Master tools through Codex app-server without an inference turn.

Uses an ephemeral in-memory host fixture, not a stored user task. Host settings
are read, never rewritten. Desktop UI and Cursor are outside this probe's scope.
"""
import argparse
import asyncio
import hashlib
import json
import os
import re
from pathlib import Path
import sys
import tomllib

REPO = Path(__file__).resolve().parents[1]


async def verify(codex: Path, config_home: Path, output: Path, server_name: str):
    codex = codex.resolve(strict=True)
    config = tomllib.loads((config_home / 'config.toml').read_text('utf-8'))
    registered = config['mcp_servers'][server_name]
    worker = Path(registered['env']['CGAL_MASTER_WORKER']).resolve(strict=True)
    worker_hash = hashlib.sha256(worker.read_bytes()).hexdigest()
    arguments = []
    for name in config.get('mcp_servers', {}):
        if name != server_name:
            assert re.fullmatch(r'[A-Za-z0-9_-]+', name), 'Unsupported dotted override key'
            arguments.extend(['-c', f'mcp_servers.{name}.enabled=false'])
    process = await asyncio.create_subprocess_exec(str(codex), *arguments, 'app-server',
        cwd=REPO, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, env={**os.environ, 'CODEX_HOME': str(config_home)})
    serial = 0
    pending = {}
    async def read_output():
        while line := await process.stdout.readline():
            value = json.loads(line)
            if 'id' in value and value['id'] in pending:
                pending.pop(value['id']).set_result(value)
            elif 'id' in value and 'method' in value:
                # Unexpected interactive server requests are not automatically approved.
                process.stdin.write((json.dumps({'id': value['id'], 'error': {
                    'code': -32601, 'message': 'Unsupported in deterministic host probe'}}) + '\n').encode())
        for future in list(pending.values()):
            if not future.done():
                future.set_exception(RuntimeError('Codex app-server stdout closed before its response'))
    async def drain_stderr():
        while await process.stderr.read(8192):
            pass
    reader = asyncio.create_task(read_output())
    stderr = asyncio.create_task(drain_stderr())
    async def rpc(method, params):
        nonlocal serial
        serial += 1
        future = asyncio.get_running_loop().create_future()
        pending[serial] = future
        process.stdin.write((json.dumps({'id': serial, 'method': method, 'params': params}) + '\n').encode())
        await process.stdin.drain()
        value = await asyncio.wait_for(future, 30)
        if 'error' in value:
            raise RuntimeError(value['error'])
        return value['result']
    try:
        initialization = await rpc('initialize', {'clientInfo': {
            'name': 'cgal_master_local_acceptance', 'version': '0.1'},
            'capabilities': {'experimentalApi': True}})
        print('Codex app-server initialized', flush=True)
        process.stdin.write(b'{"method":"initialized","params":{}}\n')
        thread = await rpc('thread/start', {'cwd': str(REPO), 'ephemeral': True,
            'approvalPolicy': 'never'})
        assert thread['thread']['ephemeral'] is True
        print('Codex in-memory host fixture initialized', flush=True)
        identifier = thread['thread']['id']
        inventory = await rpc('mcpServerStatus/list', {'threadId': identifier,
            'serverName': server_name, 'detail': 'toolsAndAuthOnly', 'limit': 10})
        server = next(entry for entry in inventory['data'] if entry['name'] == server_name)
        names = sorted(server['tools'])
        assert len(names) == 12, names
        async def tool(name, arguments):
            response = await rpc('mcpServer/tool/call', {'threadId': identifier,
                'server': server_name, 'tool': name, 'arguments': arguments})
            assert not response.get('isError'), response
            return response.get('structuredContent') or json.loads(''.join(
                item.get('text', '') for item in response['content']))
        health = await tool('cgal_system_health', {})
        print('Installed Codex host: 12 tools discovered, health called', flush=True)
        fixture = REPO / 'tests/fixtures/master/cube_with_interior.xyz'
        source = await tool('cgal_artifact_import', {'path': str(fixture), 'unit': 'mm',
            'artifact_type': 'PointSet3'})
        plan = await tool('cgal_plan', {'request': {'operation_id': 'hull.convex_3',
            'inputs': [source['artifact_id']]}})
        job = await tool('cgal_execute', {'plan_id': plan['plan_id']})
        deadline = asyncio.get_running_loop().time() + 60
        while True:
            state = await tool('cgal_job_status', {'job_id': job['job_id']})
            if state['state'] not in ('queued', 'running'):
                break
            if asyncio.get_running_loop().time() > deadline:
                await tool('cgal_job_cancel', {'job_id': job['job_id']})
                raise TimeoutError('Host hull exceeded 60s')
            await asyncio.sleep(.1)
        assert state['state'] == 'succeeded', state
        assert state['validation_status'] == 'passed', state
        artifact = await tool('cgal_artifact_inspect', {'artifact_id': state['outputs'][0]['artifact_id']})
        report = {'schema_version': 1, 'scope': 'installed_codex_app_server_host', 'status': 'pass',
            'ephemeral': True, 'inference_turn_started': False, 'desktop_ui_verified': False,
            'cursor_verified': False, 'standalone_accepted': False, 'tools': names,
            'codex_binary_sha256': hashlib.sha256(codex.read_bytes()).hexdigest(),
            'worker_sha256': worker_hash,
            'generator_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'input_sha256': source['sha256'], 'output_sha256': artifact['sha256'],
            'operations': [step['operation'] for step in plan['steps']],
            'validation_status': state['validation_status']}
        assert hashlib.sha256(worker.read_bytes()).hexdigest() == worker_hash, 'Worker changed during probe'
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(
            (json.dumps(report, indent=2) + '\n').encode())
        print('Installed Codex host -> generic hull -> mandatory validation -> Artifact: PASS', flush=True)
    finally:
        process.stdin.close()
        try:
            await asyncio.wait_for(process.wait(), 10)
        except TimeoutError:
            process.kill()
            await process.wait()
        reader.cancel()
        stderr.cancel()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex', type=Path, required=True)
    parser.add_argument('--config-home', type=Path,
        default=Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))))
    parser.add_argument('--server', default='cgal-master')
    parser.add_argument('--output', type=Path, required=True)
    arguments = parser.parse_args()
    asyncio.run(verify(arguments.codex, arguments.config_home, arguments.output, arguments.server))


if __name__ == '__main__':
    main()

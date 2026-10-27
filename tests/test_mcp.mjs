// MCP 客户端冒烟测试：initialize → tools/list → tools/call
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';

// 用仓库相对路径，避免把作者机器的绝对路径带进仓库
const HERE = path.dirname(fileURLToPath(import.meta.url));
const SERVER = process.env.DAFEIYU_MCP_ENTRY ?? path.join(HERE, '..', 'mcp-server.mjs');

const transport = new StdioClientTransport({
  command: process.env.DAFEIYU_NODE ?? 'node',
  args: [SERVER],
});
const client = new Client({ name: 'smoke', version: '1.0.0' }, { capabilities: {} });

await client.connect(transport);
console.log('== 已连接 ==');

const tools = await client.listTools();
console.log('工具:', tools.tools.map((t) => t.name).join(', '));

const write = await client.callTool({
  name: 'dafeiyu_write',
  arguments: {
    text: '主人今天问起了 MCP 工具层怎么接',
    source: 'owner',
    tags: ['部署'],
    level: 'normal',
  },
});
console.log('write ->', write.content[0].text.replace(/\s+/g, ' ').slice(0, 120));

const search = await client.callTool({
  name: 'dafeiyu_search',
  arguments: { query: 'MCP 接入', top: 3 },
});
const parsed = JSON.parse(search.content[0].text);
console.log('search ->', parsed.hits.map((h) => `${h.score} ${h.text.slice(0, 24)}`).join(' | ') || '(空)');

const stats = await client.callTool({ name: 'dafeiyu_stats', arguments: {} });
console.log('stats ->', stats.content[0].text.replace(/\s+/g, ' ').slice(0, 160));

await client.close();
console.log('== 测试结束 ==');

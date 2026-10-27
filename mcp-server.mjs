// 大肥鱼记忆 · MCP 工具层（stdio）
//
// 由 DSH 的 MCP 客户端 spawn。工具直接打通"按需检索"，解决
// 「自动注入的索引跟当前问题无关」这个天花板：
//   - auto-memory 负责常驻事实（每轮无脑注入）
//   - 这里负责长尾回忆（需要的时候才查）
//
// 设计要点：
//   1. 记忆服务不在就自己拉起来（自包含，避免"忘了起服务"这种低级失败）；
//   2. 只读 + 写入两类工具，不改配置、不碰进程；
//   3. 任何异常都以 MCP 的 isError 返回，不让客户端崩。
import { spawn } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { z } from 'zod';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const API = process.env.DAFEIYU_API ?? 'http://127.0.0.1:8730';
const TOKEN = process.env.DAFEIYU_TOKEN ?? '';
const PY = process.env.DAFEIYU_PYTHON ?? '/usr/bin/python3';

function headers() {
  const h = { 'Content-Type': 'application/json' };
  if (TOKEN) h.Authorization = `Bearer ${TOKEN}`;
  return h;
}

async function health() {
  try {
    const res = await fetch(`${API}/health`, { signal: AbortSignal.timeout(1500) });
    return res.ok;
  } catch {
    return false;
  }
}

/** 记忆服务没起来就拉起来（detached，不阻塞 MCP 启动）。 */
async function ensureService() {
  if (await health()) return true;
  try {
    const child = spawn(
      PY,
      [path.join(__dirname, 'server.py'), '--port', '8730', '--db', path.join(__dirname, 'data', 'memory.db')],
      { detached: true, stdio: 'ignore' },
    );
    child.unref();
  } catch {
    return false;
  }
  for (let i = 0; i < 20; i += 1) {
    await new Promise((r) => setTimeout(r, 250));
    if (await health()) return true;
  }
  return false;
}

async function call(pathname, body) {
  const res = await fetch(`${API}${pathname}`, {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify(body ?? {}),
    signal: AbortSignal.timeout(20000),
  });
  const data = await res.json();
  if (!data.ok) throw new Error(data.error ?? 'memory api error');
  return data;
}

const text = (obj) => ({ content: [{ type: 'text', text: JSON.stringify(obj, null, 2) }] });

const server = new McpServer(
  { name: 'dafeiyu-memory', version: '0.1.0' },
  {
    instructions:
      '大肥鱼记忆系统的长尾检索层。auto-memory 已经负责常驻事实，这里用于回忆具体发生过的事、' +
      '当时的原话与细节。只在需要具体回忆时调用，不要每轮都查。',
  },
);

server.registerTool(
  'dafeiyu_search',
  {
    title: '检索长尾记忆',
    description:
      '按查询检索大肥鱼记忆库（图扩散 + 词法 + 权重/分区/多样性打分）。用于回忆具体事件、原话、细节；' +
      '常驻事实（身份、偏好、硬约束）由 auto-memory 自动注入，不必在这里查。',
    inputSchema: {
      query: z.string().describe('要检索的内容，用自然语言'),
      top: z.number().int().min(1).max(20).optional().describe('返回条数，默认 5'),
      temperature: z
        .enum(['focused', 'normal', 'diffuse'])
        .optional()
        .describe('回忆温度：focused 更确定，diffuse 更发散'),
    },
  },
  async ({ query, top, temperature }) => {
    if (!(await ensureService())) return { ...text({ error: '记忆服务未就绪' }), isError: true };
    const data = await call('/search', { query, top: top ?? 5, temperature: temperature ?? 'normal' });
    return text({
      hits: data.hits.map((h) => ({
        text: h.text,
        score: Number(h.score.toFixed(3)),
        region: h.region,
        level: h.level,
        tags: h.tags,
        detail: h.detail,
      })),
    });
  },
);

server.registerTool(
  'dafeiyu_write',
  {
    title: '写入一条长尾记忆',
    description:
      '写入一条"发生过的事/具体细节"到长尾记忆库。注意：身份、偏好、硬约束这类常驻事实请用 auto-memory 的 ' +
      'memory_write（会自动注入每一轮），这里只放需要按需检索的细节。',
    inputSchema: {
      text: z.string().describe('记忆正文，写清楚"谁在什么情况下做了什么/说了什么"'),
      source: z.enum(['owner', 'other']).optional().describe('来源：owner 权重更高'),
      region: z.string().optional().describe('分区，如 chat/project/general'),
      tags: z.array(z.string()).optional().describe('标签'),
      level: z.enum(['core', 'important', 'normal']).optional().describe('等级，影响遗忘速度'),
      arousal: z.number().min(0).max(1).optional().describe('情绪唤醒，>=0.8 会成为闪光灯记忆（不淘汰）'),
    },
  },
  async (args) => {
    if (!(await ensureService())) return { ...text({ error: '记忆服务未就绪' }), isError: true };
    const data = await call('/add', args);
    return text({ id: data.id, merged: data.merged, surprise: Number((data.surprise ?? 0).toFixed(3)), w0: data.w0 });
  },
);

server.registerTool(
  'dafeiyu_stats',
  {
    title: '记忆库状态',
    description: '查看记忆库规模、热/冷/巩固/淘汰分布与分区统计。',
    inputSchema: {},
  },
  async () => {
    if (!(await ensureService())) return { ...text({ error: '记忆服务未就绪' }), isError: true };
    const res = await fetch(`${API}/stats`, { headers: headers(), signal: AbortSignal.timeout(8000) });
    const data = await res.json();
    return text(data.stats ?? data);
  },
);

await server.connect(new StdioServerTransport());

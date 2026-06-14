import { expect, test } from '@playwright/test';

const capabilities = {
  chat: true,
  rag: true,
  tracing: true,
  streaming: true,
  feedback: true,
  graph_version: 'lpe-agent-v1',
  corpus_version: 'test-v1',
};

let districtRequests = 0;
let transactionRequests: URL[] = [];

test.beforeEach(async ({ page }) => {
  districtRequests = 0;
  transactionRequests = [];
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    if (!url.pathname.startsWith('/api/')) return route.fallback();
    if (url.pathname === '/api/capabilities') return route.fulfill({ json: capabilities });
    if (url.pathname === '/api/meta') return route.fulfill({ json: { total: 466368, from: '2021-01-01', to: '2026-04-30' } });
    if (url.pathname === '/api/districts') {
      districtRequests += 1;
      return route.fulfill({ json: { type: 'FeatureCollection', features: [] } });
    }
    if (url.pathname === '/api/district-stats') {
      districtRequests += 1;
      return route.fulfill({ json: [] });
    }
    if (url.pathname === '/api/transactions') {
      transactionRequests.push(url);
      return route.fulfill({ json: { mode: 'clusters', cells: [] } });
    }
    if (url.pathname.endsWith('/history')) return route.fulfill({ json: { postcode: 'SW11 4NB', count: 1, truncated: false, entries: [{ id: '00000000-0000-4000-8000-000000000001', price: 485000, date: '2024-03-01', type: 'F', tenure: 'L', is_new: false, paon: '12', saon: null, street: 'EXAMPLE ROAD', town: 'LONDON' }] } });
    if (url.pathname === '/api/chat/stream') {
      const response = {
        run_id: '00000000-0000-4000-8000-000000000002',
        reply: 'SW11 recorded 100 sales.',
        citations: [],
        steps: [{ name: 'execute_sql_tools', status: 'completed', detail: 'Executed aggregate tool', duration_ms: 10 }],
        map_action: { kind: 'highlight_district', payload: { district: 'SW11' }, label: 'Highlight SW11' },
        degraded: false,
        metrics: { route: 'sql', latency_ms: 50, input_tokens: 10, output_tokens: 8, estimated_cost_usd: 0.001, graph_version: 'lpe-agent-v1', prompt_hash: 'abc', model: 'test', corpus_version: 'test-v1' },
      };
      const body = `event: run_started\ndata: {"run_id":"${response.run_id}"}\n\nevent: final\ndata: ${JSON.stringify(response)}\n\n`;
      return route.fulfill({ status: 200, contentType: 'text/event-stream', body });
    }
    if (url.pathname.endsWith('/feedback')) return route.fulfill({ json: { accepted: true, trace_attached: true } });
    return route.fulfill({ status: 404, json: { error: { code: 'NOT_FOUND', message: 'Not found' } } });
  });
});

test('toolbar and filter controls drive live transaction query params', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name === 'mobile', 'desktop toolbar menus are intentionally collapsed on mobile');
  await page.goto('/');
  await page.getByRole('button', { name: /1 Apr 2024/ }).click();
  await page.getByRole('dialog', { name: 'date menu' }).getByRole('button', { name: 'All available dates' }).click();
  await page.getByRole('button', { name: 'All property types' }).click();
  await page.getByRole('dialog', { name: 'property menu' }).getByRole('button', { name: 'Terraced' }).click();
  await page.getByRole('button', { name: 'Leasehold' }).click();
  await page.getByRole('button', { name: 'Apply filters' }).click();
  await expect.poll(() => transactionRequests.some((url) => url.searchParams.get('types') === 'T' && url.searchParams.get('tenures') === 'L')).toBe(true);

  await page.getByLabel('Search addresses, postcodes, stations, areas').fill('SW11 4NB');
  await page.getByLabel('Search addresses, postcodes, stations, areas').press('Enter');
  await expect(page.getByRole('heading', { name: 'SW11 4NB' })).toBeVisible();
});

test('reviewer can stream an answer and apply a map proposal', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('London Property Explorer')).toBeVisible();
  expect(districtRequests).toBe(0);
  await page.getByRole('button', { name: 'Assistant' }).click();
  await page.getByLabel('Ask the property assistant').fill('Show SW11 sales');
  await page.getByTitle('Send message').click();
  await expect(page.getByText('SW11 recorded 100 sales.')).toBeVisible();
  await page.getByRole('button', { name: 'Highlight SW11' }).click();
  await expect(page.getByRole('button', { name: 'Undo' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Districts' })).toHaveClass('active');
  await expect.poll(() => districtRequests).toBe(2);
  await page.getByRole('button', { name: 'Undo' }).click();
  await expect(page.getByRole('button', { name: 'Districts' })).not.toHaveClass('active');
});

test('mobile controls fit the viewport', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await page.getByRole('button', { name: 'Filters', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Filters' })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
  expect(overflow).toBe(false);
});

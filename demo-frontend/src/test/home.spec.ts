import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import HomeView from '@/views/HomeView.vue'
import { i18n, setLocale } from '@/i18n'

describe('unified demo home', () => {
  it('renders the fixed title, subtitle, and every capability entry in English', async () => {
    setLocale('en')
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      const data = url.endsWith('/api/capabilities')
        ? { catalog: { available: true, product_count: 50000, bytes: 1 }, public_set: { available: true, session_count: 200 }, openai_configured: false, trace_url: 'http://127.0.0.1:3000', limits: { native: 200, 'simulator-benchmark': 200, 'simulator-realistic': 100 } }
        : url.endsWith('/api/settings')
          ? { provider: 'local', model: 'gpt-5.5', base_url: 'https://api.openai.com/v1', realistic_verbalizer: 'template', revision: 1, openai_configured: false, model_presets: [] }
          : { runs: [] }
      return new Response(JSON.stringify(data), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }))
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: HomeView }, { path: '/:pathMatch(.*)*', component: { template: '<div />' } }] })
    await router.push('/')
    await router.isReady()
    const wrapper = mount(HomeView, { global: { plugins: [createPinia(), i18n, router] } })
    await flushPromises()

    expect(wrapper.get('h1').text()).toBe('Shopping Copilot Demo')
    expect(wrapper.get('.hero-copy h2').text()).toBe('Narrow Shopping Agent')
    expect(wrapper.get('.shopping-visual img').attributes('src')).toBe('/hero-shopping-v2.png')
    for (const label of ['Human Shopping Copilot', 'Native Evaluator', 'User Simulator · Benchmark', 'User Simulator · Realistic', 'Trace Visualizer', 'OpenAI & Models', 'Run History']) {
      expect(wrapper.text()).toContain(label)
    }
    expect(wrapper.findAll('.feature-card')).toHaveLength(7)
  })
})

import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import App from '@/App.vue'
import { i18n, setLocale } from '@/i18n'

afterEach(() => vi.unstubAllGlobals())

describe('primary navigation', () => {
  it('hides the TechJam simulator entry while keeping its deep-link route available', async () => {
    setLocale('zh-CN')
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/api/capabilities')) return Response.json({ catalog: { available: true }, public_set: { available: true } })
      if (url.endsWith('/api/settings')) return Response.json({ provider: 'local', model: 'local', base_url: 'https://api.deepseek.com', realistic_verbalizer: 'template', reranker: 'precise', revision: 0, deepseek_configured: false, model_presets: [] })
      return Response.json({ runs: [] })
    }))
    const EmptyView = { template: '<div />' }
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', component: EmptyView },
        { path: '/chat', component: EmptyView },
        { path: '/evaluations/native', component: EmptyView },
        { path: '/evaluations/simulator-techjam', component: EmptyView },
        { path: '/evaluations/simulator-realistic', component: EmptyView },
        { path: '/runs', component: EmptyView },
        { path: '/trace', component: EmptyView },
        { path: '/settings', component: EmptyView },
      ],
    })
    await router.push('/chat')
    await router.isReady()
    const wrapper = mount(App, { global: { plugins: [createPinia(), i18n, router] } })
    await flushPromises()

    expect(wrapper.get('nav').text()).not.toContain('模拟器 · TechJam')
    expect(router.resolve('/evaluations/simulator-techjam').matched).toHaveLength(1)
  })
})

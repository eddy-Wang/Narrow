import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { i18n, setLocale } from '@/i18n'
import SettingsView from '@/views/SettingsView.vue'

afterEach(() => {
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

describe('DeepSeek API key settings', () => {
  it('submits a pasted key once, never stores it, and clears the password field', async () => {
    setLocale('en')
    const secret = 'sk-test-only-browser-secret'
    const baseSettings = {
      provider: 'local', model: 'deepseek-v4-flash', base_url: 'https://api.deepseek.com',
      realistic_verbalizer: 'template', reranker: 'precise', revision: 1,
      deepseek_configured: false, model_presets: ['deepseek-v4-flash', 'deepseek-v4-pro'],
    }
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url === '/api/settings/deepseek/key') {
        return Response.json({ ...baseSettings, revision: 2, deepseek_configured: true })
      }
      if (url === '/api/settings') return Response.json(baseSettings)
      if (url === '/api/evaluations') return Response.json({ runs: [] })
      return Response.json({
        catalog: { available: true, product_count: 1, bytes: 1 },
        public_set: { available: true, session_count: 200 }, deepseek_configured: false,
        trace_url: 'http://127.0.0.1:3000', limits: { native: 200, 'simulator-techjam': 200, 'simulator-realistic': 100 },
      })
    })
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(SettingsView, { global: { plugins: [createPinia(), i18n] } })
    await flushPromises()

    const input = wrapper.get<HTMLInputElement>('[data-testid="deepseek-key-input"]')
    expect(input.attributes('type')).toBe('password')
    expect(input.attributes('autocomplete')).toBe('new-password')
    await input.setValue(secret)
    await wrapper.get('form.key-entry').trigger('submit')
    await flushPromises()

    const keyCall = fetchMock.mock.calls.find(([url]) => String(url) === '/api/settings/deepseek/key')
    expect(keyCall?.[1]?.method).toBe('PUT')
    expect(JSON.parse(String(keyCall?.[1]?.body))).toEqual({ api_key: secret })
    expect(input.element.value).toBe('')
    expect(wrapper.text()).toContain('API key saved')
    expect(wrapper.text()).not.toContain(secret)
    expect(localStorage.getItem('DEEPSEEK_API_KEY')).toBeNull()
  })
})

// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { Plagiarism } from './Plagiarism'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

it('requires demo consent and never retries an unsuccessful start on its own', async () => {
  const fetch = vi.fn(async (_url: string, options: RequestInit) =>
    options.method === 'POST'
      ? Response.json({ detail: 'Antiplagiat is disabled' }, { status: 503 })
      : Response.json({ items: [], limit: 10, offset: 0 }),
  )
  vi.stubGlobal('fetch', fetch)
  const client = new QueryClient()
  render(
    <QueryClientProvider client={client}>
      <Plagiarism versionId="demo" student />
    </QueryClientProvider>,
  )
  await screen.findByText('Эту версию ещё не проверяли.')
  const button = screen.getByRole<HTMLButtonElement>('button', {
    name: 'Запустить проверку',
  })
  expect(button.disabled).toBe(true)
  expect(
    fetch.mock.calls.some(([, options]) => options.method === 'POST'),
  ).toBe(false)
  fireEvent.click(screen.getByRole('checkbox'))
  fireEvent.click(button)
  await screen.findByText('Проверка заимствований отключена в этом окружении.')
  await waitFor(() => expect(button.disabled).toBe(false))
  const posts = fetch.mock.calls.filter(
    ([, options]) => options.method === 'POST',
  )
  expect(posts).toHaveLength(1)
  expect(posts[0][1].body).toBe('{"confirm_demo_document":true}')
  expect(new Headers(posts[0][1].headers).get('X-CSRF-Protection')).toBe('1')
  client.clear()
})

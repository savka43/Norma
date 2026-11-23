export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

const messages: Record<number, string> = {
  400: 'Запрос не удалось обработать.',
  401: 'Войдите в аккаунт, чтобы продолжить.',
  403: 'У вас нет доступа к этому действию.',
  404: 'Запись не найдена.',
  409: 'Данные изменились или действие уже выполняется. Обновите страницу и попробуйте снова.',
  413: 'Файл превышает допустимый размер.',
  415: 'Выберите файл DOCX.',
  422: 'Проверьте введённые данные.',
  503: 'Сервис сейчас недоступен.',
}

const details: Record<string, string> = {
  'Email already registered': 'Этот email уже зарегистрирован.',
  'Invalid email or password': 'Неверный email или пароль.',
  'Antiplagiat is disabled':
    'Проверка заимствований отключена в этом окружении.',
  'Document is locked while a stage is in review':
    'Документ на проверке. Дождитесь решения руководителя.',
  'Stage plan is locked during or after review':
    'План закреплён, пока есть этапы на проверке или завершённые этапы.',
  'Stage deadline outside thesis dates':
    'Срок этапа должен быть в пределах дат ВКР.',
  'This version already has an active check':
    'Проверка этой версии уже запущена.',
}

type Options = Omit<RequestInit, 'body'> & { json?: unknown; body?: BodyInit }

async function request(path: string, { json, body, ...options }: Options = {}) {
  const headers = new Headers(options.headers)
  const method = options.method ?? 'GET'
  if (method !== 'GET') headers.set('X-CSRF-Protection', '1')
  if (json !== undefined) headers.set('Content-Type', 'application/json')
  let response: Response
  try {
    response = await fetch(`/api/v1${path}`, {
      ...options,
      credentials: 'same-origin',
      method,
      headers,
      body: json === undefined ? body : JSON.stringify(json),
    })
  } catch (error) {
    if (options.signal?.aborted) throw error
    throw new ApiError(
      0,
      'Не удалось связаться с сервером. Проверьте подключение.',
    )
  }
  if (!response.ok) {
    const payload: { detail?: unknown } = await response
      .json()
      .catch(() => ({}))
    const detail = typeof payload?.detail === 'string' ? payload.detail : ''
    throw new ApiError(
      response.status,
      details[detail] ?? messages[response.status] ?? 'Запрос не выполнен.',
    )
  }
  return response
}

export async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  return (await request(path, { signal })).json() as Promise<T>
}

export async function send<T>(path: string, options: Options): Promise<T> {
  const response = await request(path, options)
  return (response.status === 204 ? undefined : await response.json()) as T
}

export async function download(path: string, json: unknown, filename: string) {
  const response = await request(path, { method: 'POST', json })
  const url = URL.createObjectURL(await response.blob())
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 0)
}

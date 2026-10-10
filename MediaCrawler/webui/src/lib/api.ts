import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// Types
export interface CrawlerConfig {
  platform: string
  login_type: string
  crawler_type: string
  keywords: string
  start_page: number
  enable_comments: boolean
  enable_sub_comments: boolean
  save_option: string
  cookies: string
  headless: boolean
}

export interface CrawlerStatus {
  status: 'idle' | 'running' | 'stopping' | 'error'
  platform: string | null
  crawler_type: string | null
  started_at: string | null
  error_message: string | null
}

export interface LogEntry {
  id: number
  timestamp: string
  level: 'info' | 'warning' | 'error' | 'success' | 'debug'
  message: string
}

export interface DataFile {
  name: string
  path: string
  size: number
  modified_at: number
  record_count: number | null
  type: string
}

export interface FilePreviewResponse {
  data: Record<string, unknown>[]
  total: number
  columns?: string[]
  sheets?: string[]
  sheet?: string
}

export interface Platform {
  value: string
  label: string
  icon: string
}

export interface ConfigOption {
  value: string
  label: string
}

// API functions
export const crawlerApi = {
  start: (config: CrawlerConfig) => api.post('/crawler/start', config),
  stop: () => api.post('/crawler/stop'),
  getStatus: () => api.get<CrawlerStatus>('/crawler/status'),
  getLogs: (limit = 100) => api.get<{ logs: LogEntry[] }>('/crawler/logs', { params: { limit } }),
}

export const dataApi = {
  getTasks: (keyword = '') => api.get<{ tasks: CollectionTask[] }>('/data/tasks', { params: { keyword } }),
  deleteTask: (id: string) => api.delete('/data/tasks/' + id),
  deleteFile: (path: string) => api.delete('/data/files/' + encodeURIComponent(path)),
  getTaskExportUrl: (id: string) => '/api/data/tasks/' + id + '/export',
  getFiles: (platform?: string, fileType?: string) =>
    api.get<{ files: DataFile[] }>('/data/files', { params: { platform, file_type: fileType } }),
  getFileContent: (path: string, limit = 100, sheet?: string) =>
    api.get<FilePreviewResponse>('/data/files/' + encodeURIComponent(path), { params: { preview: true, limit, sheet } }),
  getStats: () => api.get('/data/stats'),
  getDownloadUrl: (path: string) => `/api/data/download/${encodeURIComponent(path)}`,
}

export interface CollectionTask {
  id: string
  platform: string
  crawler_type: string
  keywords: string
  specified_ids: string
  creator_ids: string
  save_option: string
  status: string
  created_at: string
  finished_at: string | null
  files: DataFile[]
  enable_comments: boolean
  enable_sub_comments: boolean
  start_page: number
  exit_code: number | null
}

export const configApi = {
  getPlatforms: () => api.get<{ platforms: Platform[] }>('/config/platforms'),
  getOptions: () =>
    api.get<{
      login_types: ConfigOption[]
      crawler_types: ConfigOption[]
      save_options: ConfigOption[]
    }>('/config/options'),
}

export interface EnvCheckResult {
  success: boolean
  message: string
  output?: string
  error?: string
}

export const envApi = {
  check: () => api.get<EnvCheckResult>('/env/check'),
}

export default api

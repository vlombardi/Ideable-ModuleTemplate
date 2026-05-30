/**
 * API service for ModuleTemplate frontend
 * Handles communication with the ModuleTemplate backend
 */

import { getEnv } from '@/config/oidc'
import { getCurrentAccessToken } from './authToken'

const API_BASE_URL = getEnv('VITE_TEMPLATE_API_URL', '/module/template/api')

export interface TemplateItem {
  id: number
  name: string
  description: string | null
  au_creation_timestamp: string
  au_last_update_timestamp: string
  au_created_by_user: string | null
  au_last_updated_by_user: string | null
}

export interface TemplateItemCreate {
  name: string
  description?: string | null
}

export interface TemplateItemUpdate {
  name?: string | null
  description?: string | null
}

export interface TemplateItemsQuery {
  skip?: number
  limit?: number
  id?: string
  name?: string
  description?: string
  au_creation_timestamp?: string
  au_last_update_timestamp?: string
  au_created_by_user?: string
  au_last_updated_by_user?: string
  sort_by?: string
  sort_order?: 'asc' | 'desc'
}

export interface TemplateItemsPage {
  items: TemplateItem[]
  total: number
  page: number
  size: number
  pages: number
}

class TemplateApiError extends Error {
  constructor(
    message: string,
    public statusCode?: number,
    public response?: Response
  ) {
    super(message)
    this.name = 'TemplateApiError'
  }
}

async function fetchWithAuth(url: string, options: RequestInit = {}): Promise<Response> {
  const token = getCurrentAccessToken()

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...((options.headers as Record<string, string>) || {}),
  }

  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }

  const response = await fetch(url, {
    ...options,
    headers,
  })

  if (!response.ok) {
    if (response.status === 401) {
      window.dispatchEvent(new CustomEvent('auth:session-expired'))
      throw new TemplateApiError('Session expired', response.status, response)
    }
    if (response.status === 403) {
      throw new TemplateApiError('Permission denied', response.status, response)
    }
    const errorText = await response.text()
    throw new TemplateApiError(
      `API Error: ${response.status} - ${errorText}`,
      response.status,
      response
    )
  }

  return response
}

export const templateItemsService = {
  /**
   * List all template items
   */
  async listItems(query: TemplateItemsQuery = {}): Promise<TemplateItemsPage> {
    const params = new URLSearchParams()

    if (typeof query.skip === 'number') params.set('skip', String(query.skip))
    if (typeof query.limit === 'number') params.set('limit', String(query.limit))
    if (query.id && query.id.trim() !== '') params.set('id', query.id)
    if (query.name && query.name.trim() !== '') params.set('name', query.name)
    if (query.description && query.description.trim() !== '') params.set('description', query.description)
    if (query.au_creation_timestamp && query.au_creation_timestamp.trim() !== '') {
      params.set('au_creation_timestamp', query.au_creation_timestamp)
    }
    if (query.au_last_update_timestamp && query.au_last_update_timestamp.trim() !== '') {
      params.set('au_last_update_timestamp', query.au_last_update_timestamp)
    }
    if (query.au_created_by_user && query.au_created_by_user.trim() !== '') {
      params.set('au_created_by_user', query.au_created_by_user)
    }
    if (query.au_last_updated_by_user && query.au_last_updated_by_user.trim() !== '') {
      params.set('au_last_updated_by_user', query.au_last_updated_by_user)
    }
    if (query.sort_by && query.sort_by.trim() !== '' && query.sort_order) {
      params.set('sort_by', query.sort_by)
      params.set('sort_order', query.sort_order)
    }

    const queryString = params.toString()
    const url = queryString ? `${API_BASE_URL}/items?${queryString}` : `${API_BASE_URL}/items`

    const response = await fetchWithAuth(url)
    return response.json()
  },

  /**
   * Create a new template item
   */
  async createItem(data: TemplateItemCreate): Promise<TemplateItem> {
    const response = await fetchWithAuth(`${API_BASE_URL}/items`, {
      method: 'POST',
      body: JSON.stringify(data),
    })
    return response.json()
  },

  /**
   * Update an existing template item
   */
  async updateItem(id: number, data: TemplateItemUpdate): Promise<TemplateItem> {
    const response = await fetchWithAuth(`${API_BASE_URL}/items/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    })
    return response.json()
  },

  /**
   * Delete a template item
   */
  async deleteItem(id: number): Promise<void> {
    await fetchWithAuth(`${API_BASE_URL}/items/${id}`, {
      method: 'DELETE',
    })
  },
}

export default templateItemsService

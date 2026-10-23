/**
 * API 客户端测试。
 *
 * 重点：幂等键的生成必须在不支持 `crypto.randomUUID` 的环境里也能工作。
 * 项目默认通过局域网 http://<ip> 访问（非安全上下文），那里没有 randomUUID，
 * 之前直接调用它会让刷题页的「下一题」永远失败。
 */

import { afterEach, describe, expect, it, vi } from 'vitest'
import { createIdempotencyKey } from './client'

const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

describe('createIdempotencyKey', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('优先使用 crypto.randomUUID', () => {
    const key = createIdempotencyKey()
    expect(typeof key).toBe('string')
    expect(key.length).toBeGreaterThan(0)
  })

  it('没有 randomUUID 时降级到 getRandomValues，仍产出 v4 UUID', () => {
    vi.stubGlobal('crypto', {
      getRandomValues: (bytes: Uint8Array) => {
        for (let index = 0; index < bytes.length; index += 1) bytes[index] = index * 7
        return bytes
      },
    })

    expect(createIdempotencyKey()).toMatch(UUID_V4)
  })

  it('完全没有 Web Crypto 时仍返回可用且唯一的键', () => {
    vi.stubGlobal('crypto', {})

    const first = createIdempotencyKey()
    const second = createIdempotencyKey()

    expect(first).toMatch(/^k-/)
    expect(first).not.toBe(second)
  })

  it('crypto 整个不存在时也不抛异常', () => {
    vi.stubGlobal('crypto', undefined)
    expect(() => createIdempotencyKey()).not.toThrow()
  })
})

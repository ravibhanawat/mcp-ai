/**
 * Async generator that reads a fetch() Response.body stream and yields
 * typed event objects: { type: string, payload: object }
 *
 * Handles SSE frame format:
 *   event: <type>\n
 *   data: <json>\n
 *   \n
 */
export async function* parseSSE(response) {
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    // Frames are separated by double newline
    const frames = buffer.split('\n\n')
    buffer = frames.pop() // last element may be an incomplete frame

    for (const frame of frames) {
      if (!frame.trim()) continue
      let eventType = 'message'
      let data = ''
      for (const line of frame.split('\n')) {
        if (line.startsWith('event: ')) eventType = line.slice(7).trim()
        else if (line.startsWith('data: ')) data = line.slice(6).trim()
      }
      if (!data) continue
      try {
        yield { type: eventType, payload: JSON.parse(data) }
      } catch {
        // skip malformed frame silently
      }
    }
  }
}

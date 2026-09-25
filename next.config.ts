import type { NextConfig } from "next";

/**
 * The API sits behind a same-origin rewrite rather than being called
 * cross-origin from the browser. That buys three things worth one extra hop
 * (~5-15ms in-region): the session cookie is same-origin, so there is no
 * third-party-cookie problem and no CORS preflight on every call; the FastAPI
 * origin need not be publicly addressable; and the platform's WAF applies
 * before a request costs us a Python worker. See architecture.md section 3.
 */
const API_ORIGIN = process.env.API_ORIGIN ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  /**
   * Next compresses proxied responses, including `text/event-stream`, and gzip
   * buffers: the browser's EventSource then receives nothing until the buffer
   * flushes, which on an idle job stream is never. There is no per-route
   * compression switch, so it is off here.
   *
   * This costs nothing in production: Vercel (and any CDN in front of another
   * host) compresses at the edge, which is where it belongs. In local dev the
   * payloads are small and same-machine.
   */
  compress: false,

  async rewrites() {
    return [{ source: "/v1/:path*", destination: `${API_ORIGIN}/v1/:path*` }];
  },
};

export default nextConfig;

import type { NextResponse } from 'next/server';
import {
  fetchWorker,
  forwardWorkerJsonResponse,
  workerUnavailableResponse,
} from '@/lib/serverStore';

export async function POST(request: Request): Promise<NextResponse> {
  const rawBody = await request.arrayBuffer();
  const stripeSignature = request.headers.get('stripe-signature') ?? '';

  const workerRes = await fetchWorker(request, '/v1/billing/webhooks/stripe', {
    method: 'POST',
    extraHeaders: {
      'content-type': 'application/json',
      ...(stripeSignature ? { 'stripe-signature': stripeSignature } : {}),
    },
    body: rawBody,
  });

  if (!workerRes) {
    return workerUnavailableResponse();
  }

  return forwardWorkerJsonResponse(workerRes);
}

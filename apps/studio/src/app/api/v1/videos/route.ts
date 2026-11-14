import { NextResponse } from 'next/server';
import { fetchFromWorker, getStudioStore } from '@/lib/serverStore';
import type { VideoJobRecord } from '@/types/studio';

export async function GET(request: Request): Promise<NextResponse> {
  const { searchParams } = new URL(request.url);
  const workspaceId = searchParams.get('workspace_id');
  const query = workspaceId
    ? `?workspace_id=${encodeURIComponent(workspaceId)}`
    : '';

  const workerRes = await fetchFromWorker(`/v1/videos${query}`, {
    method: 'GET',
  });

  if (workerRes && workerRes.ok) {
    const workerJobs = (await workerRes.json()) as VideoJobRecord[];
    const normalized = workerJobs.map((job) => ({
      ...job,
      final_mp4_url: job.final_mp4_url
        ? `/api/v1/renders/${job.id}`
        : null,
    }));
    return NextResponse.json(normalized, { status: 200 });
  }

  const store = getStudioStore();
  const filtered = workspaceId
    ? store.jobs.filter((job) => job.workspace_id === workspaceId)
    : store.jobs;

  return NextResponse.json(filtered, { status: 200 });
}

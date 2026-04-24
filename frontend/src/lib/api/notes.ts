import type { NoteRow, AccordRow, NoteDetail, AccordDetail } from "./types";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export async function fetchTopNotes(limit = 50): Promise<NoteRow[]> {
  const res = await fetch(`${API_BASE}/api/v1/notes/top?limit=${limit}`);
  if (!res.ok) throw new Error(`fetchTopNotes: ${res.status}`);
  return res.json();
}

export async function fetchTopAccords(limit = 50): Promise<AccordRow[]> {
  const res = await fetch(`${API_BASE}/api/v1/accords/top?limit=${limit}`);
  if (!res.ok) throw new Error(`fetchTopAccords: ${res.status}`);
  return res.json();
}

export async function fetchNotesSearch(q: string, limit = 20): Promise<NoteRow[]> {
  if (!q.trim()) return [];
  const params = new URLSearchParams({ q: q.trim(), limit: String(limit) });
  const res = await fetch(`${API_BASE}/api/v1/notes/search?${params}`);
  if (!res.ok) throw new Error(`fetchNotesSearch: ${res.status}`);
  return res.json();
}

export async function fetchNoteDetail(noteName: string): Promise<NoteDetail> {
  const res = await fetch(`${API_BASE}/api/v1/notes/${encodeURIComponent(noteName)}`);
  if (!res.ok) throw new Error(`fetchNoteDetail: ${res.status}`);
  return res.json();
}

export async function fetchAccordDetail(accordName: string): Promise<AccordDetail> {
  const res = await fetch(`${API_BASE}/api/v1/accords/${encodeURIComponent(accordName)}`);
  if (!res.ok) throw new Error(`fetchAccordDetail: ${res.status}`);
  return res.json();
}

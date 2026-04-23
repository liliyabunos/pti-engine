import { NextResponse } from "next/server";

export const runtime = "edge";

export function GET() {
  return NextResponse.json({ ok: true }, { status: 200 });
}

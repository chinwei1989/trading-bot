import { NextResponse } from "next/server";

async function digest(value: string): Promise<string> {
  const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return [...new Uint8Array(bytes)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export async function POST(request: Request) {
  const expected = process.env.DASHBOARD_PASSWORD;
  if (!expected) {
    return NextResponse.json(
      { ok: false, error: "DASHBOARD_PASSWORD is not configured." },
      { status: 400 },
    );
  }
  let supplied = "";
  try {
    const body = (await request.json()) as { password?: string };
    supplied = String(body.password || "");
  } catch {
    return NextResponse.json({ ok: false, error: "Invalid request." }, { status: 400 });
  }
  if (!supplied || supplied !== expected) {
    return NextResponse.json({ ok: false, error: "Invalid password." }, { status: 401 });
  }
  const token = await digest(expected);
  const secure = new URL(request.url).protocol === "https:" ? "; Secure" : "";
  return NextResponse.json(
    { ok: true },
    {
      headers: {
        "Set-Cookie": `nova_auth=${token}; Path=/; HttpOnly; SameSite=Lax; Max-Age=43200${secure}`,
      },
    },
  );
}

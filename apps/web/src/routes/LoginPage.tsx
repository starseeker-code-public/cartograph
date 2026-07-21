import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useState } from "react";

import { api, ApiError } from "../lib/api";

export function LoginPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post("/api/auth/login", { email, password });
      // Drop every cached query — MapPage would otherwise mount against the
      // stale 401 in the ["me"] cache and bounce straight back here.
      queryClient.clear();
      await navigate({ to: "/" });
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Login failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex h-full items-center justify-center bg-slate-900">
      <form
        onSubmit={submit}
        className="w-80 space-y-4 rounded-xl bg-slate-800 p-8 shadow-xl"
      >
        <h1 className="text-xl font-semibold text-white">Cartograph</h1>
        <p className="text-sm text-slate-400">Dispatcher sign-in</p>
        <input
          type="email"
          required
          placeholder="Email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="w-full rounded-md bg-slate-700 px-3 py-2 text-sm text-white placeholder-slate-400 outline-none focus:ring-2 focus:ring-sky-500"
        />
        <input
          type="password"
          required
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="w-full rounded-md bg-slate-700 px-3 py-2 text-sm text-white placeholder-slate-400 outline-none focus:ring-2 focus:ring-sky-500"
        />
        {error && <p className="text-sm text-red-400">{error}</p>}
        <button
          type="submit"
          disabled={busy}
          className="w-full rounded-md bg-sky-600 py-2 text-sm font-medium text-white hover:bg-sky-500 disabled:opacity-50"
        >
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}

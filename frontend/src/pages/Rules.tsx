import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { api, type RulesResponse, type ApiError } from "@/lib/api";
import { isAuthed, setToken } from "@/lib/auth";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/input";

export default function Rules() {
  const { data, refetch } = useQuery<RulesResponse>({
    queryKey: ["rules"],
    queryFn: api.getRules,
  });
  const [draft, setDraft] = useState<string>("");
  const [authed, setAuthed] = useState(isAuthed());
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("axon-admin");
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (data && draft === "") setDraft(data.yaml);
  }, [data, draft]);

  async function login() {
    setError(null);
    try {
      const t = await api.login(username, password);
      setToken(t.access_token);
      setAuthed(true);
    } catch (e) {
      setError((e as ApiError).detail);
    }
  }

  async function save() {
    setError(null);
    setStatus("Saving…");
    try {
      await api.putRules(draft);
      setStatus("Saved — restart fusion to apply.");
      await refetch();
    } catch (e) {
      setStatus(null);
      setError((e as ApiError).detail);
    }
  }

  return (
    <div className="grid grid-cols-12 gap-4">
      <div className="col-span-12 lg:col-span-8">
        <Card>
          <CardHeader>
            <CardTitle>fusion rules.yaml</CardTitle>
            <Badge variant="muted">
              {data?.path ?? "loading…"}
            </Badge>
          </CardHeader>
          <CardBody className="space-y-3">
            <Textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              rows={28}
              spellCheck={false}
              className="w-full"
            />
            <div className="flex items-center gap-2">
              <Button onClick={save} disabled={!authed}>
                Save
              </Button>
              <Button
                variant="secondary"
                onClick={() => setDraft(data?.yaml ?? "")}
              >
                Revert
              </Button>
              {status ? <span className="text-sm text-emerald-700">{status}</span> : null}
              {error ? <span className="text-sm text-rose-700">{error}</span> : null}
              {!authed ? (
                <span className="ml-auto text-xs text-amber-700">
                  Log in (right) to enable saving.
                </span>
              ) : null}
            </div>
          </CardBody>
        </Card>
      </div>

      <div className="col-span-12 lg:col-span-4 space-y-4">
        <Card>
          <CardHeader>
            <CardTitle>Admin sign-in</CardTitle>
            <Badge variant={authed ? "success" : "muted"}>
              {authed ? "authenticated" : "anonymous"}
            </Badge>
          </CardHeader>
          <CardBody className="space-y-2">
            <Input
              placeholder="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
            />
            <Input
              type="password"
              placeholder="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
            />
            <Button onClick={login}>Sign in</Button>
          </CardBody>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Notes</CardTitle>
          </CardHeader>
          <CardBody className="text-xs text-slate-500">
            <ul className="list-disc space-y-1 pl-4">
              <li>YAML is validated against <code>FusionConfig</code> before write.</li>
              <li>Fusion reads the file at startup — restart it to apply.</li>
              <li>Single hardcoded admin user for the MVP; production swaps in the university SSO.</li>
            </ul>
          </CardBody>
        </Card>
      </div>
    </div>
  );
}

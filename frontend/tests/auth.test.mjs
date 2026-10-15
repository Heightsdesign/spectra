import test from "node:test";
import assert from "node:assert/strict";
import { validateAuth } from "../src/lib/auth-validation.ts";
import { loadCustomer } from "../src/lib/customer.ts";
import { language, messages } from "../src/lib/i18n.ts";

const valid = { email: "collector@example.com", password: "a-long-unique-password", confirm: "a-long-unique-password", first_name: "Camille", last_name: "Martin" };
test("valid registration and login values", () => {
  assert.equal(validateAuth("register", valid), null);
  assert.equal(validateAuth("login", valid), null);
});
test("registration validates email, names and password bounds", () => {
  for (const overrides of [{ email: "invalid" }, { first_name: " " }, { last_name: "a\nb" }, { password: "short" }, { password: "x".repeat(129) }]) assert.equal(validateAuth("register", { ...valid, ...overrides }), "invalid_input");
});
test("reset and registration require matching passwords", () => {
  for (const mode of ["register", "reset"]) assert.equal(validateAuth(mode, { ...valid, confirm: "different" }), "mismatch");
});
test("login and reset request validation", () => {
  assert.equal(validateAuth("login", { ...valid, password: "" }), "invalid_input");
  assert.equal(validateAuth("forgot", { email: "bad" }), "invalid_input");
});
test("FR and EN dictionary keys stay in sync", () => {
  assert.deepEqual(Object.keys(messages.FR).sort(), Object.keys(messages.EN).sort());
  assert.equal(language("EN"), "EN"); assert.equal(language("unknown"), "FR");
});
test("protected account lookup uses backend authentication and never caches", async () => {
  let received;
  const customer = { id: "test-id", email_verified: true, preferred_language: "FR" };
  const request = async (url, options) => { received = { url, options }; return new Response(JSON.stringify(customer), { status: 200 }); };
  const result = await loadCustomer("spectra_session=opaque", "http://backend", request);
  assert.equal(result.status, "authenticated");
  assert.equal(received.url, "http://backend/api/auth/me");
  assert.equal(received.options.headers.Cookie, "spectra_session=opaque");
  assert.equal(received.options.cache, "no-store");
});
test("missing or forged sessions cannot unlock account rendering", async () => {
  for (const cookie of ["", "spectra_session=forged"]) {
    const result = await loadCustomer(cookie, "http://backend", async () => new Response("{}", { status: 401 }));
    assert.equal(result.status, "unauthorized");
  }
});
test("backend outage and unverified data fail closed", async () => {
  for (const request of [async () => { throw new Error("down"); }, async () => new Response("{}", { status: 503 }), async () => new Response(JSON.stringify({ id: "x", email_verified: false, preferred_language: "FR" }))]) {
    assert.equal((await loadCustomer("cookie", "http://backend", request)).status, "unavailable");
  }
});

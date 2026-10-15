import test from "node:test";
import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import { join } from "node:path";

test("real Next proxy, backend sessions and protected account routes", async () => {
  const base = process.env.SPECTRA_INTEGRATION_URL;
  const folder = process.env.SPECTRA_TEST_MAIL;
  const email = process.env.SPECTRA_TEST_EMAIL;
  assert.ok(base && folder && email, "Run through tests/run-local-integration.py");
  const password = "Integration-password-2026!";
  let cookie = "";
  async function request(path, payload, csrf, origin = base) {
    return fetch(base + path, { method: payload === undefined ? "GET" : path.endsWith("/profile") ? "PATCH" : "POST", redirect: "manual",
      headers: { Cookie: cookie, ...(payload === undefined ? {} : { "Content-Type": "application/json", Origin: origin, "X-Spectra-Client": "1", ...(csrf ? { "X-CSRF-Token": csrf } : {}) }) },
      ...(payload === undefined ? {} : { body: JSON.stringify(payload) }) });
  }
  async function token(purpose) {
    const messages = await Promise.all((await readdir(folder)).filter(n => n.endsWith(".json")).map(async n => JSON.parse(await readFile(join(folder, n), "utf8"))));
    const mail = messages.find(m => m.recipient === email && m.purpose === purpose);
    assert.ok(mail);
    return new URLSearchParams(new URL(mail.link).hash.slice(1)).get("token");
  }
  for (const path of ["/account", "/account/settings"]) {
    const result = await request(path);
    assert.equal(result.status, 307);
    assert.equal(result.headers.get("location"), "/login");
  }
  for (const path of ["/register", "/login", "/verify-email", "/forgot-password", "/reset-password"]) assert.equal((await request(path)).status, 200);
  const english = await fetch(base + "/register", { headers: { Cookie: "spectra_language=EN" } });
  assert.match(await english.text(), /Create an account/);
  assert.equal((await request("/api/auth/register", { email, password, first_name: "Collector", last_name: "Smoke", preferred_language: "FR" })).status, 202);
  const verifyToken = await token("verify");
  const verification = await Promise.all([request("/api/auth/verify-email", { token: verifyToken }), request("/api/auth/verify-email", { token: verifyToken })]);
  assert.deepEqual(verification.map(r => r.status).sort(), [200, 400]);
  let login = await request("/api/auth/login", { email, password });
  assert.equal(login.status, 200);
  const setCookie = login.headers.get("set-cookie");
  assert.match(setCookie, /HttpOnly/);
  cookie = setCookie.split(";")[0];
  assert.match(await (await request("/account")).text(), /Mes soumissions/);
  let csrf = (await (await request("/api/auth/csrf")).json()).csrf_token;
  assert.equal((await request("/api/auth/profile", { first_name: "A", last_name: "B", preferred_language: "EN" }, csrf, "https://evil.example")).status, 403);
  assert.equal((await request("/api/auth/profile", { first_name: "Collector", last_name: "Smoke", preferred_language: "EN" }, csrf)).status, 200);
  assert.match(await (await request("/account")).text(), /My submissions/);
  // Real PostgreSQL transactions via Next proxy, including simultaneous requests.
  async function submission(path, method = "GET", payload) {
    return fetch(base + "/api/submissions" + path, {method, headers: {Cookie:cookie, Origin:base, "Content-Type":"application/json", "X-Spectra-Client":"1", "X-CSRF-Token":csrf}, ...(payload ? {body:JSON.stringify(payload)} : {})});
  }
  let response = await submission("", "POST", {});
  assert.equal(response.status,201);
  let draft = await response.json();
  const path = "/" + draft.id;
  const card = {game:"pokemon",card_name:"Pikachu",expansion:"Base",card_number:"58",language:"FR",quantity:2,notes:""};
  response = await submission(path+"/entries","POST",{...card,version:draft.version});
  assert.equal(response.status,201);
  draft=await response.json();
  const edits=await Promise.all([submission(path,"PATCH",{version:draft.version,notes:"A"}),submission(path,"PATCH",{version:draft.version,notes:"B"})]);
  assert.deepEqual(edits.map(r=>r.status).sort(),[200,409]);
  draft=await (await submission(path)).json();
  const race=await Promise.all([submission(path+"/confirm","POST",{version:draft.version}),submission(path+"/entries","POST",{...card,version:draft.version})]);
  assert.ok(race.some(r=>r.status===409));
  draft=await (await submission(path)).json();
  if(draft.status==='draft') {
    assert.equal((await submission(path+'/confirm','POST',{version:draft.version})).status,200);
    draft=await (await submission(path)).json();
  }
  const confirmations=await Promise.all([submission(path+'/confirm','POST',{version:1}),submission(path+'/confirm','POST',{version:1})]);
  for(const result of confirmations) {assert.equal(result.status,200);assert.deepEqual(await result.json(),draft);}
  assert.equal((await submission(path,'PATCH',{version:draft.version,notes:'forbidden'})).status,409);
  assert.match(await (await request('/account/submissions/'+draft.id)).text(), /My submissions/);
  assert.equal((await request('/api/auth/profile',{first_name:'Collector',last_name:'Smoke',preferred_language:'FR'},csrf)).status,200);
  assert.match(await (await request('/account/submissions/'+draft.id)).text(), /Mes soumissions/);
  assert.equal((await submission('')).status,200);
  // W3.2: the production Next proxy exposes an authenticated example catalog,
  // per-entry selections, immutable snapshots and the separate acceptance flow.
  const catalogResponse = await submission('/catalog');
  assert.equal(catalogResponse.status,200);
  const catalog = await catalogResponse.json();
  assert.equal(catalog.development_only,true);
  assert.deepEqual(Object.keys(catalog.tiers),['standard','express','priority']);
  assert.ok(Object.values(catalog.tiers).every(t=>t.estimated_turnaround===null));
  let priced = await (await submission('', 'POST', {})).json();
  const pricedPath = '/' + priced.id;
  priced = await (await submission(pricedPath+'/entries','POST',{...card,version:priced.version,quantity:2})).json();
  priced = await (await submission(pricedPath+'/entries','POST',{...card,card_name:'Luffy',version:priced.version,quantity:3,processing_tier:'express',upgrade_ids:['detailed']})).json();
  let pricedQuoteResponse = await submission(pricedPath+'/quotes','POST',{version:priced.version});
  assert.equal(pricedQuoteResponse.status,201);
  let pricedQuote = await pricedQuoteResponse.json();
  assert.equal(pricedQuote.snapshot.quantity,5);
  assert.equal(pricedQuote.snapshot.total_minor,7400);
  assert.equal(pricedQuote.snapshot.lines.length,2);
  const quoteRetry = await submission(pricedPath+'/quotes','POST',{version:priced.version});
  assert.deepEqual(await quoteRetry.json(),pricedQuote);
  const configuration = {version:priced.version,processing_tier:'priority',upgrade_ids:['classic']};
  const changes = await Promise.all([submission(pricedPath+'/configuration','PATCH',configuration),submission(pricedPath+'/configuration','PATCH',configuration)]);
  assert.deepEqual(changes.map(r=>r.status).sort(),[200,409]);
  priced = await (await submission(pricedPath)).json();
  const historical = await (await submission(pricedPath+'/quotes/'+pricedQuote.id)).json();
  assert.equal(historical.status,'invalidated');
  assert.deepEqual(historical.snapshot,pricedQuote.snapshot);
  assert.equal((await submission(pricedPath+'/quotes','POST',{version:priced.version,total_minor:1})).status,422);
  pricedQuote = await (await submission(pricedPath+'/quotes','POST',{version:priced.version})).json();
  assert.equal(pricedQuote.snapshot.total_minor,10000);
  priced = await (await submission(pricedPath+'/confirm','POST',{version:priced.version})).json();
  assert.equal((await (await submission(pricedPath+'/quotes/'+pricedQuote.id)).json()).status,'valid');
  const terms = await submission(pricedPath+'/quotes/'+pricedQuote.id+'/accept','POST',{version:priced.version,accept_terms:true});
  assert.equal(terms.status,409);
  assert.equal((await terms.json()).detail,'example_terms_not_acceptable');
  assert.equal((await submission(pricedPath+'/configuration','PATCH',{...configuration,version:priced.version})).status,409);
  // W3.3: address ownership/CSRF through the real Next proxy and pending checkout.
  async function addressRequest(path='',method='GET',payload){return fetch(base+'/api/addresses'+path,{method,headers:{Cookie:cookie,Origin:base,'Content-Type':'application/json','X-Spectra-Client':'1','X-CSRF-Token':csrf},...(payload?{body:JSON.stringify(payload)}:{})});}
  const addressData={recipient:'Test Collector',line1:'Test Street',city:'Test City',postal_code:'75001',country:'FR',phone:'+33123456789'};
  const createdAddressResponse=await addressRequest('','POST',addressData);assert.equal(createdAddressResponse.status,201);
  const createdAddress=await createdAddressResponse.json();
  assert.equal((await addressRequest()).status,200);
  let orderResponse=await submission(pricedPath+'/order-summary');assert.equal(orderResponse.status,200);
  let order=await orderResponse.json();assert.equal(order.final_payable_minor,null);assert.ok(order.readiness.states.includes('missing_return_address'));
  const delivery={version:0,address_id:createdAddress.id,declared_value_minor:12345};
  orderResponse=await submission(pricedPath+'/delivery','PUT',delivery);assert.equal(orderResponse.status,200);order=await orderResponse.json();
  assert.equal(order.return_address.id,createdAddress.id);assert.equal(order.shipping.charge_minor,null);assert.equal(order.final_payable_minor,null);assert.ok(order.readiness.states.includes('shipping_price_pending'));
  assert.equal((await submission(pricedPath+'/delivery','PUT',delivery)).status,409);
  assert.equal((await addressRequest('/'+createdAddress.id,'DELETE',{version:1})).status,409);
  assert.equal((await submission(pricedPath+'/quotes/'+pricedQuote.id)).status,200);
  assert.equal((await (await submission(pricedPath+'/quotes/'+pricedQuote.id)).json()).status,'invalidated');
  assert.equal((await addressRequest('/'+createdAddress.id,'PUT',{...addressData,version:1,city:'Updated'})).status,200);
  assert.match(await (await request('/account/settings')).text(),/Adresses de retour/);
  assert.equal((await request('/api/auth/profile',{first_name:'Collector',last_name:'Smoke',preferred_language:'EN'},csrf)).status,200);
  assert.match(await (await request('/account/settings')).text(),/Return addresses/);
  // Entry data loads client-side; SSR exposes the authenticated language shell.
  assert.match(await (await request('/account/submissions/'+priced.id)).text(),/My submissions/);
  assert.equal((await request("/api/auth/logout", {}, csrf)).status, 200);
  assert.equal((await request("/account")).status, 307);
  cookie = "";
  assert.equal((await request("/api/auth/password/reset/request", { email })).status, 202);
  const newPassword = "Replacement-password-2026!";
  assert.equal((await request("/api/auth/password/reset", { token: await token("reset"), password: newPassword })).status, 200);
  login = await request("/api/auth/login", { email, password: newPassword });
  assert.equal(login.status, 200);
  cookie = login.headers.get("set-cookie").split(";")[0];
  csrf = (await (await request("/api/auth/csrf")).json()).csrf_token;
  assert.equal((await request("/api/auth/password/change", { current_password: newPassword, new_password: password }, csrf)).status, 200);
  assert.equal((await request("/account/settings")).status, 307);
});

// Reads `npm audit --json` on stdin. Fails on any high or critical advisory unless
// audit-exceptions.json accepts it with a reason and a date that has not passed (T20).
// An exception past its date fails too, so an accepted risk gets looked at again.
import { readFileSync } from "node:fs";

const audit = JSON.parse(readFileSync(0, "utf8"));
const { exceptions } = JSON.parse(readFileSync(new URL("../audit-exceptions.json", import.meta.url), "utf8"));
const today = new Date().toISOString().slice(0, 10);

const advisories = new Map();
for (const vulnerability of Object.values(audit.vulnerabilities ?? {})) {
  for (const via of vulnerability.via) {
    if (typeof via === "object" && ["high", "critical"].includes(via.severity)) {
      advisories.set(via.url.split("/").pop(), `${via.severity} ${via.name}: ${via.title}`);
    }
  }
}

let failed = false;
for (const [id, description] of advisories) {
  const exception = exceptions.find((e) => e.id === id);
  if (!exception) {
    console.log(`FAIL ${id} ${description}`);
    failed = true;
  } else if (exception.until < today) {
    console.log(`FAIL ${id} accepted until ${exception.until}, look at it again: ${description}`);
    failed = true;
  } else {
    console.log(`accepted until ${exception.until}: ${id} ${description}`);
  }
}
console.log(`${advisories.size} high or critical advisories, ${failed ? "not all accepted" : "all accepted"}`);
process.exit(failed ? 1 : 0);

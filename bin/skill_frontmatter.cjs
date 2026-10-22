const fs = require('node:fs');
const { createRequire } = require('node:module');
const { isDeepStrictEqual } = require('node:util');

try {
  const backendRequire = createRequire(fs.realpathSync(process.argv[2]));
  const matter = backendRequire('gray-matter');
  const yaml = backendRequire('js-yaml');
  const { target, sources, generated } = JSON.parse(fs.readFileSync(0, 'utf8'));
  const outputs = new Map(generated.map(entry => [entry.id, entry]));
  const sourceIds = new Set(sources.map(entry => entry.id));
  const fields = ['name', 'description', 'license', 'compatibility', 'metadata', 'allowed-tools'];
  const object = value => value !== null && typeof value === 'object' && Object.getPrototypeOf(value) === Object.prototype;
  const valid = (field, value) => {
    if (field === 'metadata') return object(value) && Object.values(value).every(item => typeof item === 'string');
    return typeof value === 'string';
  };
  const fail = (id, field, reason) => { throw new Error(`${target}: skill ${id}: ${field}: ${reason}`); };
  for (const entry of generated) {
    if (!sourceIds.has(entry.id)) fail(entry.id, 'source', 'generated skill has no matching source');
  }
  for (const entry of sources) {
    const id = entry.id;
    let source;
    try { source = matter(Buffer.from(entry.sourceBase64, 'base64').toString('utf8')).data; }
    catch (error) { fail(id, 'frontmatter', error.message); }
    const targets = source.targets ?? ['*'];
    if (!Array.isArray(targets) || !targets.every(value => typeof value === 'string')) fail(id, 'targets', 'expected an array of strings');
    if (!targets.includes('*') && !targets.includes(target)) continue;
    const expectedFields = {};
    for (const field of fields) {
      let expected = source[field];
      const sectionFields = target === 'claudecode' || target === 'opencode'
        ? ['license', 'compatibility', 'metadata'] : target === 'cursor' ? ['metadata'] : [];
      if (sectionFields.includes(field) && source[target]?.[field] != null) expected = source[target][field];
      if (expected === undefined) continue;
      if (!valid(field, expected)) fail(id, field, 'unsupported source value type');
      expectedFields[field] = expected;
    }
    const output = outputs.get(id);
    if (!output) fail(id, 'output', 'targeted skill was not generated');
    const text = Buffer.from(output.generatedBase64, 'base64').toString('utf8');
    let result;
    try { result = matter(text).data; }
    catch (error) { fail(id, 'generated frontmatter', error.message); }
    let changed = false;
    for (const [field, expected] of Object.entries(expectedFields)) {
      if (field === 'license' && result[field] === undefined && ['codexcli', 'grokcli', 'claudecode', 'cursor', 'antigravity-cli'].includes(target)) {
        result[field] = expected;
        changed = true;
        continue;
      }
      if (field === 'metadata' && object(result[field])) {
        for (const [key, value] of Object.entries(expected)) {
          const mapped = target === 'codexcli' && key === 'short-description' && source.codexcli?.[key] !== undefined
            ? source.codexcli[key] : value;
          if (!Object.hasOwn(result[field], key) || !isDeepStrictEqual(result[field][key], mapped)) fail(id, `metadata.${key}`, 'missing or conflicting generated value');
        }
      } else if (!isDeepStrictEqual(result[field], expected)) {
        fail(id, field, 'missing or conflicting generated value');
      }
    }
    if (changed) {
      const header = /^---\r?\n[\s\S]*?\r?\n---(?=\r?\n|$)/.exec(text);
      if (!header) fail(id, 'generated frontmatter', 'missing YAML delimiters');
      const replacement = `---\n${yaml.dump(result, { lineWidth: -1, noRefs: true })}---${text.slice(header[0].length)}`;
      output.generatedBase64 = Buffer.from(replacement, 'utf8').toString('base64');
    }
  }
  process.stdout.write(JSON.stringify({ generated }));
} catch (error) {
  process.stderr.write(`${error.message}\n`);
  process.exitCode = 1;
}

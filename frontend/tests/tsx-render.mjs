import { readFile } from 'node:fs/promises';
import ts from 'typescript';

// Render actual TSX with the installed compiler and Next's CommonJS interop.
export async function componentModule(relativePath) {
  const file = new URL(relativePath, import.meta.url);
  let code = ts.transpileModule(await readFile(file, 'utf8'), {
    compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  for (const [, specifier] of [...code.matchAll(/from ["']([^"']+)["']/g)]) {
    let resolved;
    if (specifier.startsWith('./')) resolved = await componentModule(new URL(specifier + '.tsx', file).href);
    else if (specifier.startsWith('@/components/')) resolved = await componentModule(new URL('../src/' + specifier.slice(2) + '.tsx', import.meta.url).href);
    else if (specifier.startsWith('@/')) resolved = new URL('../src/' + specifier.slice(2) + '.ts', import.meta.url).href;
    else if (specifier.startsWith('next/')) {
      const moduleUrl = import.meta.resolve(specifier + '.js');
      resolved = 'data:text/javascript;base64,' + Buffer.from(`import value from ${JSON.stringify(moduleUrl)}; export default value.default ?? value;`).toString('base64');
    } else resolved = import.meta.resolve(specifier);
    code = code.replaceAll(`"${specifier}"`, JSON.stringify(resolved)).replaceAll(`'${specifier}'`, JSON.stringify(resolved));
  }
  return 'data:text/javascript;base64,' + Buffer.from(code).toString('base64');
}

/**
 * Jinja2 模板变量解析器（轻量 TS 实现）
 *
 * 仅做模板字符串扫描提取变量引用，不引入 nunjucks（~300KB）。
 * 不做求值，只找出 {{ x.y.z }} 中的顶层变量名（x）。
 *
 * 支持的 Jinja2 语法子集：
 *   {{ var }}            → 顶层变量 "var"
 *   {{ a.b.c }}          → 顶层变量 "a"
 *   {{ a.b | filter }}   → 顶层变量 "a"
 *   {{ a.b | f1 | f2 }}  → 顶层变量 "a"
 *
 * 不处理：
 *   {% for ... %}        → 控制流（DSL 不允许，忽略）
 *   {% if ... %}         → 控制流（DSL 不允许，忽略）
 */

/** 匹配 {{ ... }} 表达式，捕获内容部分 */
const JINJA_EXPR_RE = /\{\{([\s\S]*?)\}\}/g;

/** 匹配 identifier（字母开头，仅含字母/数字/下划线） */
const IDENTIFIER_RE = /^([a-zA-Z_][a-zA-Z0-9_]*)/;

/**
 * 从 Jinja2 模板字符串中提取所有顶层变量引用。
 *
 * @param template - Jinja2 模板字符串，如 "Hello {{ user.name }}, id={{ start.id }}"
 * @returns 顶层变量名数组（去重），如 ["user", "start"]
 *
 * @example
 * collectVariables("{{ start.employee_id | upper }}")
 * // → ["start"]
 *
 * collectVariables("{{ llm_1.message }} and {{ start.name }}")
 * // → ["llm_1", "start"]
 */
export function collectVariables(template: string): string[] {
  const vars = new Set<string>();
  let match: RegExpExecArray | null;

  JINJA_EXPR_RE.lastIndex = 0;
  while ((match = JINJA_EXPR_RE.exec(template)) !== null) {
    const expr = match[1]?.trim() ?? '';
    // 取 | 之前的表达式部分（过滤器链的输入）
    const baseExpr = expr.split('|')[0]?.trim() ?? '';
    // 提取第一个标识符（顶层变量名）
    const identMatch = IDENTIFIER_RE.exec(baseExpr);
    if (identMatch?.[1]) {
      vars.add(identMatch[1]);
    }
  }

  return Array.from(vars);
}

/**
 * 从 Jinja2 模板中提取 varName.<field> 的字段名列表。
 *
 * @param template - Jinja2 模板字符串
 * @param varName - 要提取字段的顶层变量名（节点 ID）
 * @returns 字段名数组（可能包含重复，调用方自行去重）
 *
 * @example
 * extractFieldRefs("{{ llm_1.message | upper }}", "llm_1")
 * // → ["message"]
 *
 * extractFieldRefs("{{ start.name }} {{ start.email }}", "start")
 * // → ["name", "email"]
 */
export function extractFieldRefs(template: string, varName: string): string[] {
  // 匹配 varName.field_name（字段名：字母/数字/下划线）
  const pattern = new RegExp(
    `\\{\\{[^}]*\\b${escapeRegex(varName)}\\s*\\.\\s*([a-zA-Z_][a-zA-Z0-9_]*)`,
    'g',
  );
  const fields: string[] = [];
  let m: RegExpExecArray | null;
  while ((m = pattern.exec(template)) !== null) {
    if (m[1]) {
      fields.push(m[1]);
    }
  }
  return fields;
}

/** 转义正则特殊字符 */
function escapeRegex(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

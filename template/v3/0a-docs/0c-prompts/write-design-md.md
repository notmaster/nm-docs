# Prompt: Write DESIGN.md

本提示词用于让 AI 基于项目需求、参考资料、原型或截图编写
`0a-docs/0b-design/DESIGN.md`。输出必须遵守 Google `design.md` 官方规范。

官方参考：

- <https://github.com/google-labs-code/design.md>
- <https://github.com/google-labs-code/design.md/blob/main/docs/spec.md>

## 使用方式

将下面的提示词复制给 AI，并把实际参考资料粘贴到对应占位符中。管理员需要审阅输出，并运行：

```bash
npm run design:lint
```

或直接运行：

```bash
npx @google/design.md lint 0a-docs/0b-design/DESIGN.md
```

## 模板提示词

```text
你是一名资深产品设计系统设计师和前端设计规范作者。

请基于我提供的项目资料，编写一份可直接保存为
`0a-docs/0b-design/DESIGN.md` 的设计规范文档。

你的目标不是编写 UI 代码，而是产出一份让 AI coding agent 能稳定复现视觉风格的 DESIGN.md。

必须参考并遵守 Google design.md 官方规范：

- DESIGN.md 由两部分组成：
  1. 文件顶部的 YAML front matter，用于机器可读的 design tokens。
  2. Markdown 正文，用于人类可读的设计意图、应用规则和边界。
- YAML front matter 必须以单独一行 `---` 开始，并以单独一行 `---` 结束。
- YAML token 是规范值，正文说明这些 token 为什么存在以及如何使用。
- token schema 可包含：
  - `version`
  - `name`
  - `description`
  - `colors`
  - `typography`
  - `rounded`
  - `spacing`
  - `components`
- token reference 必须使用 `{path.to.token}` 形式，例如 `{colors.primary}`。
- component token 可包含：
  - `backgroundColor`
  - `textColor`
  - `typography`
  - `rounded`
  - `padding`
  - `size`
  - `height`
  - `width`
- Markdown 正文使用 `##` 标题。若包含以下章节，必须按此顺序出现：
  1. `## Overview`
  2. `## Colors`
  3. `## Typography`
  4. `## Layout`
  5. `## Elevation & Depth`
  6. `## Shapes`
  7. `## Components`
  8. `## Do's and Don'ts`
- 不要重复同名 `##` 章节。
- 不要引用未定义的 token。
- 颜色和组件文本/背景对比应尽量满足 WCAG AA，普通文本对比度不低于 4.5:1。
- 如果资料不足以确定某个 token，请做保守、明确、可解释的设计选择，不要输出占位符。

请特别注意：

- 设计应服务产品目标和目标用户，不要生成通用、空泛、营销化的设计语言。
- 不要使用一整套单一色相的单调配色。
- 不要默认使用大面积紫色、蓝紫渐变、米色/沙色、深蓝/石板色、棕橙/咖啡色主题，除非资料明确要求。
- 卡片圆角默认不超过 8px，除非设计语言明确需要更大圆角。
- 字间距默认使用 `0`，只有标签、全大写短文本或品牌风格明确需要时才使用正 letter spacing。
- 正文说明必须具体到如何应用，避免“现代、简洁、高级”这类无法执行的空话。
- 如果原型和需求文档冲突，以管理员明确说明为最高优先级；否则在文末列出冲突和建议。

请输出完整 DESIGN.md 内容，且只输出文档正文，不要添加解释性前后缀。

项目资料如下：

## 项目名称

<填写项目名称>

## 产品定位

<粘贴 REQUIREMENTS.md 摘要、目标用户、使用场景、核心价值>

## 验收标准

<粘贴 ACCEPTANCE.md 中与视觉、交互、可用性有关的要求>

## 原型或截图说明

<粘贴原型链接、截图说明、页面结构、关键组件、交互状态>

## 参考品牌或竞品

<粘贴参考对象、喜欢/不喜欢的点、必须避开的风格>

## 技术与实现约束

<填写技术栈、目标平台、响应式要求、字体限制、无障碍要求>

## 管理员补充要求

<填写任何必须保留、必须避免、必须强调的设计规则>

输出完成后，请自查：

1. YAML front matter 是否可以被解析。
2. 是否至少定义了 `colors.primary`。
3. 是否定义了可执行的 typography tokens。
4. component token 是否只引用已定义 token。
5. `##` 章节顺序是否符合规范。
6. 是否避免重复章节标题。
7. 是否能通过：
   `npx @google/design.md lint 0a-docs/0b-design/DESIGN.md`
```

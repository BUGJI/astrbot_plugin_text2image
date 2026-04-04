# Changelog

All notable changes to this project will be documented in this file.

## [0.4.0] - 2026-04-05

### Added
- 字体匹配支持编号匹配（`font:1` 使用第一个字体）
- CSS 参数支持引号包裹（支持值内含空格）
- 生成图片前显示预计时间
- 新增 `mode:article` 文章模式，支持保留空格换行和 CSS 定义宽度自动换行
- 新增 `ext` 扩展参数（预留 Markdown 支持）

### Improved
- `listall` 图片分页显示改进，每页顶部显示页码和使用提示
- 字体序号独立列显示，更清晰
- 渲染器 CSS 优化，支持 width 属性固定宽度
- single 模式恢复为单行横向输出

## [0.3.1] - 2026-04-04

### Fixed
- 字体加载方式：改用 base64 内嵌方式，彻底解决浏览器跨域问题
- 修复 `#listall` 指令中的 asyncio 嵌套问题
- 添加字体文件路径检测，不存在时给出警告

### Improved
- `#listall` 首次使用提示缓存时间
- 字体示例图使用相对路径引用

## [0.3.0] - 2026-04-03

### Added
- 初始版本
- 支持多种渲染模式（single/char/word/line/token）
- CSS 样式自定义
- 字体列表查看（文字/图片形式）
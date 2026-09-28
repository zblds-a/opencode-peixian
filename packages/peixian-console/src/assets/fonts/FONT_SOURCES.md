# 离线字体来源

这些字体文件随前端静态构建和 Control 镜像交付。浏览器从本站 `/assets/` 加载，不请求公网字体服务。保留各项目原始 OFL 许可证文件。

| 文件 | 官方来源 | 上游版本 | SHA-256 |
| --- | --- | --- | --- |
| `NotoSansSC.ttf` | `google/fonts/ofl/notosanssc/NotoSansSC[wght].ttf` | google/fonts `23e54b51ddffbc7713c583748e3bd86f62b1fa4a` | `a3041811a78c361b1de50f953c805e0244951c21c5bd412f7232ef0d899af0da` |
| `NotoSerifSC.ttf` | `google/fonts/ofl/notoserifsc/NotoSerifSC[wght].ttf` | 同上 | `050080d9255a86808f2945bffac582b31ef32bc36411ce29563b4961670c66f9` |
| `Inter.ttf` | `google/fonts/ofl/inter/Inter[opsz,wght].ttf` | 同上 | `029160a80ff49ddcab2c97711247e08b1fab27a484a329ce8b813d820dc559031` |
| `LXGWWenKai-Regular.ttf` | `lxgw/LxgwWenKai` 官方 release | `v1.522` | `39ad71264b588165b469e35e6afb162a378dacd1f95348160240ba9038ac3009` |

来源：<https://github.com/google/fonts/tree/23e54b51ddffbc7713c583748e3bd86f62b1fa4a/ofl>、<https://github.com/lxgw/LxgwWenKai/releases/tag/v1.522>。

字体文件保持原样；只在 CSS 中声明本地加载。Noto 与 Inter 对应 `OFL-NotoSansSC.txt`、`OFL-NotoSerifSC.txt`、`OFL-Inter.txt`，霞鹜文楷对应 `OFL-LXGWWenKai.txt`。

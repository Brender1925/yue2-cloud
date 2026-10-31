# 第三方组件与授权说明

本项目自身代码采用 MIT 协议（见 `LICENSE`）。但仓库内包含以下第三方组件，
它们**各有独立的授权条款**，分发本项目时必须一并遵守。

---

## 1. MuseScore_General.sf3（音源/SoundFont）

- **文件**：`音源/MuseScore_General.sf3`（v0.2）
- **协议**：MIT License
- **来源**：MuseScore 官方发行版内置 SoundFont
  （https://musescore.org/handbook/3/sound-and-playback/soundfonts-and-sfz-files）
- **重要义务**：MIT 要求"版权声明与许可声明必须包含在所有副本或实质性部分中"。
  下列署名**必须**随本项目一同分发：

  ```
  Fluid (R3) SoundFont — Copyright (c) 2000-2002, 2008 Frank Wen
  Mono conversion (FluidR3Mono) — Copyright (c) 2014-17 Michael Cowgill
  Adaptation for MuseScore_General.sf2 — Copyright (c) 2018-19 S. Christian Collins
  Temple Blocks instrument provided by Ethan Winer — Copyright (c) 2002
  Drumline Cymbals provided by Michael Schorsch — Copyright (c) 2016

  Permission is hereby granted, free of charge, to any person obtaining a copy
  of this software and associated documentation files (the "Software"), to deal
  in the Software without restriction, including without limitation the rights
  to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
  copies of the Software, and to permit persons to whom the Software is
  furnished to do so, subject to the following conditions:

  The above copyright notice and this permission notice shall be included in
  all copies or substantial portions of the Software.

  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
  IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
  FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
  AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
  LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
  OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
  THE SOFTWARE.
  ```

---

## 2. FluidSynth（音源/fluid/bin/）

- **文件**：`音源/fluid/bin/fluidsynth.exe` 及配套 DLL
- **协议**：GNU Lesser General Public License v2.1 or later
- **来源**：https://github.com/FluidSynth/fluidsynth
- **分发合规要点**（按 FluidSynth LicensingFAQ）：
  1. 本项目以**独立 DLL 文件**形式附带 FluidSynth，属于动态链接，不影响本项目自身
     代码采用 MIT；
  2. 用户必须能够**独立替换/升级** FluidSynth 部分——本项目已把 FluidSynth 放在
     独立目录 `音源/fluid/bin/`，使用者可直接替换整个目录；
  3. 若你对 FluidSynth 本身做过修改，修改后的版本必须以 LGPL 条款提供。
     **本仓库内的 FluidSynth 二进制为未经修改的官方 Windows 发行版。**
  4. LGPL 要求附带许可证全文——完整文本见：
     https://www.gnu.org/licenses/old-licenses/lgpl-2.1.txt
- **注意**：本仓库只含 Windows 预编译二进制，**不含 FluidSynth 源码**。
  若需要分发源码版本或自行编译，请从官方仓库获取并遵循其构建说明。

---

## 3. Python 依赖（由 pip 安装，不随仓库分发）

| 包 | 协议 |
|----|------|
| numpy | BSD-3-Clause |
| scipy | BSD-3-Clause |
| soundfile | BSD-3-Clause |
| librosa | ISC |
| mido | MIT |

---

## 4. 外部工作流与模型（运行时依赖，不随仓库分发）

`工作流/文生音乐带谱_api.json` 是一份 ComfyUI API 格式的工作流导出，其中引用了
下列外部资源，**它们不由本仓库提供，也不会被仓库分发**：

| 节点 | 依赖 | 说明 |
|------|------|------|
| 15 | `yue2_3b_bf16.safetensors` | YuE2 模型权重，需自行从官方渠道获取 |
| 39 | `MelBandRoformer_fp16.safetensors` | 分离人声模型 |
| 36 / 39 | `kijai/ComfyUI-MelBandRoFormer` | 自定义节点插件 |
| 52 | `WujiYue2Lyricist` | RunningHub 平台节点（闭源，平台侧授权） |
| 53 | `RH_Screenwriter` | RunningHub 平台节点（闭源，平台侧授权） |

**使用前请自行确认上述模型与插件的许可条款是否允许你的用途。**
本项目仅提供工作流的连接结构，不分发任何模型权重。

---

## 5. 项目自身不包含的内容

- 任何 API key、工作流 ID（`配置/云端配置.json` 已清空并列入 `.gitignore`）
- 任何生成产物（`Beat售卖/`、`生成测试/` 已列入 `.gitignore`）
- 任何第三方模型权重

<div align="center">

# 🎯 Kyoraku ParamHunter

**Advanced Parameter Discovery Tool for Authorized Security Testing**

![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)
![Version](https://img.shields.io/badge/Version-23.1-orange.svg)

</div>

---

## ⚠️ LEGAL WARNING

> **For AUTHORIZED security testing ONLY.**
>
> Using this tool against systems you don't own or have written permission
> to test is **ILLEGAL** under the Bangladesh Cyber Security Act 2023,
> CFAA, CMA and similar laws.
>
> **Read [DISCLAIMER.md](DISCLAIMER.md) before use.**

---

## 🚀 Features

- Deep crawling with BFS + depth control
- Parameter extraction from:
  - HTML forms (with source page tracking)
  - URL query strings (single-char params like `q`, `s`, `p` included)
  - JavaScript files (`.js`, `.mjs`, `.cjs`, `.jsx`)
  - JSON API responses
- Recursive JS mining (follows imports)
- Threaded live verification
- Tracking param filtering (`utm_*`, `fbclid`, `gclid`, `_ga`)
- CLI configurable
- Save results to file
- Ctrl+C safe (partial results saved)

---

## 📦 Installation

```bash
git clone https://github.com/axoterurazez29-max/Paramhunter.git
cd Paramhunter
pip install -r requirements.txt

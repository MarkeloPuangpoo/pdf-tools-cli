# PDF Tools CLI (`pdftoolscli`) — Implementation Phases

เอกสารนี้สรุปและแบ่งขั้นตอนการพัฒนาระบบ **PDF Tools CLI (`pdftoolscli`)** ออกเป็น 8 เฟส (Phase 0 ถึง Phase 7) อย่างเป็นลำดับขั้นตอน โดยอ้างอิงและยึดถือข้อกำหนดจาก [PLAN.md](file:///Users/macmarc/Documents/pdftoolscli/PLAN.md) เป็นหลักการทำงานสูงสุด (Source of Truth)

---

## สรุปภาพรวมของทุก Phase (Roadmap Overview)

| Phase | ชื่อเฟส (Designation) | วัตถุประสงค์หลัก | คำสั่งที่ครอบคลุม | ผลลัพธ์เป้าหมาย (Deliverable) | สถานะ |
|---|---|---|---|---|---|
| **Phase 0** | Repository & Engineering Foundations | ติดตั้ง Build system, Toolchains, Test harness, Native spikes | ไม่มี | Dev environment พร้อมใช้, `uv.lock`, fixture generation | `[x]` สำเร็จ |
| **Phase 1** | Core Subsystems & CLI Presentation | Range grammar, I/O safety, Process isolation, Secrets, Presenter | `completion` (C04) | Core libraries, Click root, JSON v1 envelope | `[ ]` ไม่เริ่ม |
| **Phase 2** | PDF Backend Adapters | `pikepdf` และ `pypdfium2` adapters, worker boundary | ไม่มี | Backend adapters ผ่าน contract tests บนไฟล์จริง | `[ ]` ไม่เริ่ม |
| **Phase 3** | MVP Command Suite (P1) | Core manipulation, inspection, text, encryption, lossless optimize | 16 คำสั่งหลัก (C01–C05, C09–C14, C20, C26, C31, C35–C36) | **v0.1.0 MVP Release** | `[ ]` ไม่เริ่ม |
| **Phase 4** | Core Expansion & Batch (P2) | Advanced geometry, assembly, rendering, images, metadata, stamps, batch | 23 คำสั่ง (C06–C08, C15–C18, C22–C24, C27, C29–C30, C32–C34, C37–C38, C42–C43, C45–C48) | **v0.2.0 Beta Release** พร้อม Batch Engine & Standalone Binaries | `[ ]` ไม่เริ่ม |
| **Phase 5** | Advanced Capabilities (P3) | Lossy compression, OCR, AcroForms, annotation flattening, structural repair | 7 คำสั่ง (C21, C28, C39–C41, C44, C49) | **v1.0.0 General Availability** Release | `[ ]` ไม่เริ่ม |
| **Phase 6** | Experimental Features (P4) | Booklet imposition, PDF/A-2b conversion with veraPDF validation | 2 คำสั่งทดลอง (C19, C25) | Experimental flags enabled (`PDFTOOLSCLI_EXPERIMENTAL=1`) | `[ ]` ไม่เริ่ม |
| **Phase 7** | Packaging, Distribution & Docs | PyInstaller one-dir bundles, Homebrew tap, Scoop bucket, Docs site, manpages | ครอบคลุมทุกคำสั่งที่เปิดตัว | Full Distribution Ecosystem & Public Docs | `[ ]` ไม่เริ่ม |

---

## กฎเหล็กในการดำเนินงาน (Execution Protocols)

1. **ห้ามข้ามขั้นตอน (Strict Dependency Order):** ต้องทำให้ผ่านการทดสอบ (Pass 100%) ในแต่ละ Task ก่อนจึงจะไป Task ถัดไปได้
2. **ห้ามละเมิดระบบความปลอดภัย (Safety Invariants):**
   - การเขียนไฟล์ต้องผ่าน Temporary Staging และ Atomic Rename เสมอ (`storage/atomic.py`)
   - ห้ามอนุญาตให้ `input == output` เด็ดขาด แม้จะใส่ `--overwrite`
   - ห้ามรับรหัสผ่านผ่าน flag `--password <val>` ใน CLI (ต้องใช้ file, env, stdin หรือ masked TTY เท่านั้น)
3. **Process Isolation:** ฟังก์ชันที่ใช้ C++ libraries (`libqpdf`, `PDFium`) ต้องรันใน worker process ที่ supervise โดย `runtime/supervisor.py` เสมอ เพื่อป้องกัน segfault และ OOM กระทบ process แม่
4. **Output Discipline:** Machine-readable data / JSON ส่งออกทาง `stdout`; Logs, progress bar, diagnostics ส่งออกทาง `stderr`
5. **Verification หลังจากจบทุก Task:**
   ```bash
   ruff check .
   ruff format --check .
   mypy src
   pytest
   ```
6. **Git Commit & Push ทุกครั้งที่เสร็จสิ้นงาน (Mandatory Git Push):**
   - ทุกครั้งที่ทำงานในแต่ละ Task สำเร็จและผ่านการ verify ครบถ้วน รวมถึงอัปเดต checklist เรียบร้อยแล้ว **ต้อง commit และ push ขึ้น Git repository เสมอ**:
   - Remote URL: `https://github.com/MarkeloPuangpoo/pdf-tools-cli.git`
   - รูปแบบคำสั่ง:
     ```bash
     git add .
     git commit -m "feat(<task-id>): <รายละเอียดสิ่งที่ทำ>"
     git push origin <branch>
     ```

---

## รายละเอียดแต่ละ Phase และ Checklist ติดตามงาน

### Phase 0: Repository & Engineering Foundations
> **เป้าหมาย:** สร้างรากฐานโปรเจกต์ Python, กำหนดสเปก build system, linter/type checker, ล็อก dependency hashes และสร้าง fixture generator สำหรับไฟล์ PDF

- [x] **ARCH-001: Project Scaffolding & Developer Tooling** (Completed)
  - **งาน:** สร้าง `pyproject.toml` (Hatchling backend), `.python-version` (3.12), `.gitignore`, `ruff.toml`, skeleton `src/pdftoolscli/` (`__init__.py`, `__main__.py`, `py.typed`)
  - **ทดสอบ:** `tests/test_scaffolding.py` เช็ค package import และ version export
  - **เกณฑ์สำเร็จ:** `uv sync --locked`, `ruff check .` และ `mypy src` ผ่าน 0 errors
- [x] **ARCH-002: Backend Spike Validation & Native Dependency Lock** (Completed)
  - **งาน:** Spike ทดสอบ thread-safety และ memory leak ของ `pypdfium2` และ `pikepdf`, ล็อกเวอร์ชัน wheels ใน `uv.lock`
  - **ทดสอบ:** `scripts/spike_pikepdf.py`, `scripts/spike_pdfium.py`
  - **เกณฑ์สำเร็จ:** Native handles ถูกปิดสมบูรณ์, ไม่เกิด segfault, lockfile มี SHA-256 hash ครบ
- [x] **TEST-001: PDF Test Fixture Generator & Verification Harness** (Completed)
  - **งาน:** สร้างสคริปต์ generate PDF fixture หลากหลายรูปแบบ (single-page, multi-page, rotated, encrypted, form fields, malformed) แบบ deterministic
  - **ทดสอบ:** ตรวจสอบ SHA-256 ของ fixture ที่ generate ตรงกับ manifest
  - **เกณฑ์สำเร็จ:** Fixtures พร้อมใช้งานสำหรับทุก unit และ integration tests

---

### Phase 1: Core Subsystems & CLI Presentation
> **เป้าหมาย:** พัฒนาระบบพื้นฐานของ CLI ได้แก่ ไวยากรณ์เลือกหน้า, ระบบจัดการไฟล์อย่างปลอดภัย, ระบบจัดการ Process, ระบบความลับ และ Click CLI framework

- [ ] **CORE-001: Page Range Parser, Grammar & Resolvers**
  - **งาน:** ตัวแปลง EBNF Page range (`1-5`, `even`, `odd`, `last`, `3,1,3`) พร้อมคำนวณ mapping 1-based index
  - **ทดสอบ:** Property-based testing ด้วย Hypothesis
  - **เกณฑ์สำเร็จ:** Parse ได้แม่นยำ, ปฏิเสธค่าที่ผิดพลาด (exit code 2) โดยไม่มี unhandled exception
- [ ] **CORE-002: Configuration Management & Precedence**
  - **งาน:** ระบบอ่าน config TOML/JSON ตามลำดับ priority: CLI flags > Env vars > Config file > Defaults
  - **ทดสอบ:** Test config override matrix
  - **เกณฑ์สำเร็จ:** แปลงชนิดข้อมูลถูกต้อง, ตรวจสอบ path ที่ปลอดภัย
- [ ] **IO-001: Safe File I/O, File Identity & Atomic Transactions**
  - **งาน:** ตรวจสอบ filesystem identity (`inode`/`FileIndex`) ป้องกัน `input == output`, ระบบ Atomic Publication ด้วย hardlink/rename
  - **ทดสอบ:** Fault injection (disk full, permission denied, concurrent access)
  - **เกณฑ์สำเร็จ:** ไฟล์ต้นฉบับไม่เสียหาย 100%, atomic swap ทำงานถูกต้องบน macOS, Linux และ Windows
- [ ] **SEC-001: Secret Acquisition & Security Boundary**
  - **งาน:** ตัวดึงรหัสผ่านจาก File, Env, Stdin หรือ Interactive masked prompt; ทำความสะอาด memory และ env ก่อนส่งให้ child process
  - **ทดสอบ:** ตรวจสอบ leak ใน process args, logs, และ terminal history
  - **เกณฑ์สำเร็จ:** ปฏิเสธ raw `--password` argument, masking ถูกต้อง
- [ ] **PROC-001: Process Supervisor, IPC & Resource Budgets**
  - **งาน:** ระบบ Supervisor คุม worker process ผ่าน bidirectional pipe พร้อม timeout และ memory limits (`setrlimit`/Job Objects)
  - **ทดสอบ:** Worker segfault injection, OOM simulation, timeout trigger
  - **เกณฑ์สำเร็จ:** Worker crash ถูกจับได้และคืน exit code 10, parent CLI ไม่ล่ม, ลบ scratch space สะอาด
- [ ] **OUT-001: Output Presentation Subsystem (Human / Quiet / JSON v1)**
  - **งาน:** Module นำเสนอผลลัพธ์: Human (Rich terminal format), Quiet, และ Structured JSON v1 schema
  - **ทดสอบ:** Schema validation เทียบกับ JSON Schema v1 draft
  - **เกณฑ์สำเร็จ:** stdout สะอาดเฉพาะ data/JSON, stderr ใช้สำหรับ logs/progress
- [ ] **CLI-001: Root CLI Group, Global Options & Error Boundary**
  - **งาน:** Click CLI entrypoint, global flags (`--json`, `--quiet`, `--verbose`, `--no-color`, `--config`), Error translation เป็น Exit codes 0–10
  - **ทดสอบ:** CLI runner tests สำหรับ global flags และ invalid options
  - **เกณฑ์สำเร็จ:** `pdftoolscli --help` และ `--version` ทำงานได้รวดเร็ว (<50ms) โดยไม่โหลด native PDF engines
- [ ] **CLI-002: Shell Completion Subsystem**
  - **งาน:** คำสั่ง `pdftoolscli completion <shell>` (bash, zsh, fish, powershell)
  - **ทดสอบ:** ตรวจสอบ shell script output syntax
  - **เกณฑ์สำเร็จ:** ติดตั้งและ autocomplete ชื่อคำสั่งและ flag ได้ถูกต้อง

---

### Phase 2: PDF Backend Adapters
> **เป้าหมาย:** ห่อหุ้ม native C++ libraries (`pikepdf` และ `pypdfium2`) ให้อยู่ภายใต้ domain contracts ที่ปลอดภัย

- [ ] **PDF-001: pikepdf Backend Adapter & Invariant Verification**
  - **งาน:** Adapter สำหรับ `pikepdf` ทำงานด้าน document structure, page tree, encryption, object streams
  - **ทดสอบ:** Memory leak tests หลังเปิด-ปิด 100 ไฟล์, C++ exception mapping ไปเป็น domain errors
  - **เกณฑ์สำเร็จ:** ปิด handles สะอาด, แปลง error เป็น `E_PDF_INVALID` / `E_PDF_ENCRYPTED` อย่างสมบูรณ์
- [ ] **PDF-002: pypdfium2 Backend Adapter & Process Isolation**
  - **งาน:** Adapter สำหรับ `pypdfium2` ทำงานด้าน rendering และ plain text extraction ภายใน dedicated worker process
  - **ทดสอบ:** Concurrency tests ป้องกัน thread race condition ใน PDFium
  - **เกณฑ์สำเร็จ:** 1 document ต่อ 1 worker process เท่านั้น, คืน byte array หรือ text string สมบูรณ์

---

### Phase 3: MVP Command Suite (P1)
> **เป้าหมาย:** ส่งมอบ 16 คำสั่งหลักระดับ MVP ครอบคลุมการใช้งานทั่วไปของ Developer และ Sysadmin (Release: **v0.1.0 MVP**)

- [ ] **CMD-001: Discovery & Diagnostics Commands**
  - `pdftoolscli inspect INPUT [--detail basic|all]`
  - `pdftoolscli validate INPUT [--strict]`
  - `pdftoolscli doctor [--check CAPABILITY ...]`
- [ ] **CMD-002: Core Page Operations**
  - `pdftoolscli split INPUT --output-dir DIR [--every N | --ranges GROUPS]`
  - `pdftoolscli pages extract INPUT RANGE -o OUTPUT`
  - `pdftoolscli pages remove INPUT RANGE -o OUTPUT`
  - `pdftoolscli pages reorder INPUT ORDER -o OUTPUT`
  - `pdftoolscli pages reverse INPUT -o OUTPUT`
  - `pdftoolscli pages rotate INPUT ANGLE -o OUTPUT [--pages RANGE]`
- [ ] **CMD-003: Document Concatenation**
  - `pdftoolscli merge INPUT... -o OUTPUT [--document-policy none|first]`
- [ ] **CMD-004: Encryption & Decryption**
  - `pdftoolscli encrypt INPUT -o OUTPUT [OPTIONS]` (AES-256)
  - `pdftoolscli decrypt INPUT -o OUTPUT [PASSWORD-SOURCE]`
- [ ] **CMD-005: Lossless Optimization**
  - `pdftoolscli optimize INPUT -o OUTPUT [--object-streams preserve|generate|disable]`
- [ ] **CMD-006: Plain Text Extraction**
  - `pdftoolscli text extract INPUT [--pages RANGE] [-o OUTPUT]`
- [ ] **CMD-007: Document Metadata Inspection**
  - `pdftoolscli metadata show INPUT [--source all|info|xmp]`

---

### Phase 4: Core Expansion & Batch Processing (P2)
> **เป้าหมาย:** ขยายฟังก์ชันการทำงานขั้นสูง: Batch engine (`-B`), จัดการรูปภาพ, เรนเดอร์, จัดหน้า/ขนาด, ค้นหาข้อความ, ทำลายน้ำ/เลขหน้า (Release: **v0.2.0 Beta**)

- [ ] **BATCH-001: Batch Execution Engine & Multi-File Dispatch**
  - **งาน:** ระบบรันงานแบบ batch รองรับ recursive globs, `--jobs N`, `--fail-fast`, และ structured manifest report
- [ ] **CMD-008: Advanced Page Assembly & Geometry**
  - `assemble`, `insert`, `interleave`, `pages crop`, `pages resize`, `pages boxes`, `pages duplicate`
- [ ] **CMD-009: Embedded Image Management**
  - `images list INPUT [--pages RANGE]`
  - `images extract INPUT --output-dir DIR [--mode original|decoded]`
- [ ] **CMD-010: Rendering & Conversion**
  - `render INPUT --output-dir DIR [--to png|jpeg|webp|tiff]`
  - `convert images IMAGE... -o OUTPUT` (img2pdf lossless passthrough)
  - `convert rasterize INPUT -o OUTPUT`
- [ ] **CMD-011: In-Document Text Search**
  - `text search INPUT PATTERN [--regex] [--ignore-case] [--count]`
- [ ] **CMD-012: Metadata Mutation & Sanitization**
  - `metadata set`, `metadata remove`, `metadata sanitize` (ล้าง revision ประวัติย้อนหลัง)
- [ ] **CMD-013: Stamping & Page Numbering**
  - `stamp INPUT (--text|--image|--pdf) -o OUTPUT`
  - `number INPUT --format "Page {page} of {pages}" -o OUTPUT`
- [ ] **CMD-014: Non-Widget Annotations Management**
  - `annotations list`, `annotations remove`
- [ ] **CMD-015: Document Attachments Management**
  - `attachments list`, `attachments extract`, `attachments add`, `attachments remove`

---

### Phase 5: Advanced Capabilities (P3)
> **เป้าหมาย:** ฟังก์ชันชั้นสูงที่ต้องอาศัยการคำนวณหรือ external dependencies เช่น การบีบอัดรูปภาพแบบสูญเสียรายละเอียด, OCR, แบบฟอร์ม AcroForm และการซ่อมแซมไฟล์ (Release: **v1.0.0 GA**)

- [ ] **CMD-016: Lossy Image Compression**
  - `compress INPUT -o OUTPUT --preset screen|ebook|printer|prepress|archive`
- [ ] **CMD-017: OCR Integration**
  - `ocr INPUT -o OUTPUT [--language LANG] [--mode skip|force] [--deskew] [--sidecar PATH]` (เชื่อมต่อ external `OCRmyPDF`)
- [ ] **CMD-018: Interactive Form Handling**
  - `forms list`, `forms fill`, `forms flatten` (ตรวจสอบ field name, คำนวณ appearance streams)
- [ ] **CMD-019: Annotation Flattening**
  - `annotations flatten INPUT -o OUTPUT` (แปลง appearance streams เข้าเนื้อหาหลัก)
- [ ] **CMD-020: PDF Structural Repair**
  - `repair INPUT -o OUTPUT` (กู้คืน broken xref, salvage readable streams)

---

### Phase 6: Experimental Features (P4)
> **เป้าหมาย:** คำสั่งทดลองที่แยกอยู่หลัง flag `PDFTOOLSCLI_EXPERIMENTAL=1`

- [ ] **CMD-021: Experimental Features**
  - `pages booklet INPUT --sheet A4|Letter -o OUTPUT` (จัดหน้า 2-up สำหรับพิมพ์สมุด)
  - `convert pdfa INPUT -o OUTPUT --profile pdfa-2b --icc-profile FILE` (แปลงเป็น PDF/A-2b และตรวจสอบด้วย veraPDF)

---

### Phase 7: Packaging, Distribution & Documentation
> **เป้าหมาย:** สภาพแวดล้อมการเผยแพร่แบบ Open-source, เอกสารคู่มือ, Binary packages ที่ทำงานได้โดยไม่ต้องลง Python

- [ ] **DOC-001: Documentation Architecture & Manual Generation**
  - MkDocs Material site, manpages generation, copy-pasteable CLI cookbook
- [ ] **REL-001: Packaging, Distribution & CI/CD Pipelines**
  - PyInstaller one-directory standalone builds (macOS, Linux, Windows)
  - Homebrew tap & Scoop manifest
  - GitHub Actions CI/CD matrix สำหรับ release automation

---

## ขั้นตอนถัดไปทันที (Next Action)

เริ่มลงมือทำ **Phase 0** ได้ทันที โดยเริ่มจากงาน:
👉 **`ARCH-001: Project Scaffolding & Developer Tooling`**
*(สร้าง `pyproject.toml`, กำหนด config uv/hatchling, linter ruff, mypy strict, และ package skeleton `src/pdftoolscli/`)*

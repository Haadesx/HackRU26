# HackRU26 — Automatic Development Documentation

You are my coding assistant for the HackRU 2026 project.

**GitHub repository:** https://github.com/Haadesx/HackRU26

We are developing different parts of the application independently. Your responsibility is to continuously document everything we build so our team can understand and combine all components later without losing technical details.

## 1. Identify your developer and branch

Determine which developer you are assisting:

| Developer | Component | Git Branch | Documentation File |
|---|---|---|---|
| Sinchana | Web UI | `feat/ui-sinchana` | `docs/ui-sinchana.md` |
| Aparajita | iOS Application | `feat/ios-aparajita` | `docs/ios-aparajita.md` |
| Urvi | Backend + Database | `feat/backend-urvi` | `docs/backend-urvi.md` |

If the developer's identity is unknown, ask once.

Inspect the current Git repository and preserve all existing work.

Create or switch to the assigned feature branch, ensuring it starts from the appropriate existing work and no changes are lost. If the remote repository is not initialized yet, report that blocker rather than destructively reinitializing anything.

Do not directly develop on or merge into `main`.

## 2. Maintain ONE documentation file

Create the assigned Markdown file inside `docs/`.

**This file is the single source of truth for all technical work performed on this component.**

It must be kept updated throughout development, not written only when the project is finished.

Document the following information:

### A. Component overview
- What this component does.
- Its responsibilities.
- Technologies, languages, and frameworks used.
- Current implementation status.

### B. Everything implemented
- Every major feature created.
- Functionality added, modified, or removed.
- Important classes, functions, modules, and files.
- What actually works versus what is incomplete.
- Any mock or placeholder functionality.

### C. Design and architectural decisions
- Important technical decisions.
- Why each approach was chosen.
- Alternatives considered, when relevant.
- Changes to earlier decisions.
- Assumptions and limitations.

### D. Dependencies and environment
- Every major dependency and its exact version.
- Package managers and runtime requirements.
- Installation and build commands.
- Required operating system or platform versions.
- Environment variable names and purposes (NEVER their secret values).
- External services, SDKs, and APIs.
- Dependencies likely to conflict with another component.

### E. APIs and data structures
Where applicable, document:
- API endpoints and HTTP methods.
- Request and response formats.
- JSON field names and data types.
- Authentication requirements.
- Database tables, columns, and relationships.
- Model structures and shared interfaces.
- Expected inputs and outputs.
- Error responses.
- Any breaking interface changes.

Use actual implemented contracts, not invented ones.

### F. File and folder structure
- Important directories and files.
- What each major file does.
- Entrypoints.
- Configuration locations.
- Generated files and assets needed at runtime.

### G. Setup and execution
Provide the exact commands needed to:
- Install dependencies.
- Configure the environment.
- Run the component locally.
- Run tests.
- Build the application.
- Reproduce the currently working setup.

Distinguish verified commands from untested instructions.

### H. Integration-relevant information
Record anything another developer would need to know to connect this component to theirs:
- Expected input/output data.
- Endpoint locations and configuration requirements.
- Required environment variables.
- Authentication assumptions.
- Shared types and naming conventions.
- Backend/frontend dependencies.
- Platform-specific limitations.
- Compatibility concerns.
- Breaking changes.

Do not write a separate integration plan. Just accurately document the existing technical interfaces and requirements.

### I. Testing and verification
- Tests created.
- Tests actually executed.
- Pass/fail results.
- Known bugs.
- Performance observations.
- Workarounds.
- Untested functionality.

Never report something as working unless it was actually verified.

### J. Chronological change log
Maintain an append-only log of meaningful development changes.

For each entry, include:
- Date/time.
- Feature or change made.
- Relevant files.
- Reason for the change.
- Dependencies added or removed.
- API/schema changes.
- Tests executed and results.
- Relevant commit SHA when available.

Preserve historical decisions, including superseded ones, while keeping the current-state sections accurate.

### K. Known issues and outstanding work
- Unfinished features.
- Bugs and limitations.
- Temporary workarounds.
- Missing dependencies.
- Decisions awaiting confirmation.
- Anything likely to cause integration problems.

## 3. Automatic documentation rule

**This is a standing instruction for the entire coding session and subsequent sessions that load this project guidance.**

Whenever you:
- Implement a feature.
- Modify functionality.
- Add or remove a dependency.
- Change an API.
- Change a data model or database schema.
- Modify configuration.
- Make an architectural decision.
- Fix a significant bug.
- Introduce a workaround.
- Discover a technical limitation.
- Complete a test or benchmark.

You MUST update the assigned Markdown file as part of that same task.

Do not wait for me to explicitly request documentation.

Do not leave documentation until the end of the project.

Before reporting any coding task as complete, verify that the documentation reflects the current code.

When applicable, commit the updated documentation together with the corresponding code changes.

## 4. Preserve accuracy

- Never invent completed features, tests, or capabilities.
- Explicitly mark proposed, implemented, tested, and blocked items.
- Keep dependency versions consistent with actual manifests and lockfiles.
- Update obsolete information when architecture changes.
- Preserve historical changes in the chronological log.
- Do not duplicate the same content unnecessarily.
- Do not include passwords, API keys, credentials, or private tokens.
- Do not modify unrelated components or teammates' documentation.
- Never discard existing developer work.

## 5. Git synchronization

Work only on the assigned feature branch.

As development progresses:
1. Make changes in the developer's existing project.
2. Update the assigned documentation file.
3. Run appropriate tests.
4. Commit code and documentation together.
5. Push commits to the assigned branch when authorized and Git access is available.

Never force-push, overwrite remote history, or merge into `main` without explicit authorization.

If pushing is unavailable, preserve all local work and provide the exact commands needed later.

## 6. Initial execution

Start now.

1. Inspect the existing codebase and Git state.
2. Identify the assigned developer and branch.
3. Establish the feature branch safely.
4. Create the assigned Markdown documentation file.
5. Inspect all work already completed.
6. Document the current implementation, dependencies, decisions, file structure, and relevant interfaces.
7. Clearly mark anything that cannot be verified.
8. Continue normal development while automatically maintaining the document.

**Important:** This is a persistent documentation requirement, not a one-time documentation task. If your coding tool supports project-level persistent instructions, add a minimal instruction pointing to this Markdown file so future coding sessions continue maintaining it.

Your primary development responsibilities remain unchanged. The documentation process should happen automatically alongside normal coding.

## Final requirement

At every major milestone, the documentation must accurately answer:

- What have we built?
- How does it work?
- Why was it built this way?
- What technologies and versions does it require?
- What files and interfaces does it expose?
- What is currently verified and working?
- What is unfinished or broken?
- What will another developer need to know to connect this component?

**Begin by documenting the existing work. Do not start rebuilding or replacing code that already exists.**





I am Urvi working on Backend+Database.
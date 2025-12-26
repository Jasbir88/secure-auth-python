# Changelog

All notable changes to this project will be documented here.

This project follows **Semantic Versioning** (https://semver.org).

---

## [0.1.0] - 2025-01-XX

### Added
- Argon2 password hashing (OWASP recommended)
- Password verification with defensive failure handling
- Password rehash detection for future upgrades
- Password validation with blacklist enforcement
- Unicode-safe password handling
- CI pipeline with GitHub Actions
- Comprehensive test suite

### Security
- Memory-hard password hashing
- Timing-safe verification
- Blacklist of common weak passwords

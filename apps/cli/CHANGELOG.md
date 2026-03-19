# Changelog

All notable changes to the Modal Scripts CLI will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Initial release of Modal Scripts CLI
- Clean, minimalistic TUI inspired by Claude CLI
- Script discovery and execution
- Keyboard navigation (↑↓/jk for navigation, Enter to execute, q to quit)
- Script icons based on file extension
- Script descriptions support
- Environment variable configuration (MODAL_SCRIPTS_DIR)
- Command-line argument support (--dir, --debug)
- Automatic script categorization by file type (.sh, .py, .js, .ts)
- Script execution feedback with duration tracking
- Return to menu after script completion
- Window resize handling
- Color-coded output (success/error states)
- Help command (? or h)
- Setup script for easy installation
- Comprehensive documentation (README, QUICKSTART, CONTRIBUTING)
- TypeScript support with full type definitions
- Prettier integration for code formatting
- Utility functions for colors, formatting, and helpers

### Technical Details
- Built with Bun runtime
- Powered by OpenTUI framework
- TypeScript for type safety
- Modular architecture with separated concerns
- Customizable color scheme
- Support for multiple script types

## [0.1.0] - 2024-01-XX

### Added
- Initial project setup
- Core TUI functionality
- Script execution engine
- Documentation suite

---

## Version History

### Planned Features (Future Releases)

#### v0.2.0
- [ ] Script search/filter functionality
- [ ] Favorites/pinned scripts
- [ ] Script history tracking
- [ ] Execution logs viewer
- [ ] Script categories/tags
- [ ] Custom key bindings

#### v0.3.0
- [ ] Script metadata extraction from comments
- [ ] Parallel script execution
- [ ] Script dependencies management
- [ ] Environment variable templating
- [ ] Script templates

#### v1.0.0
- [ ] Production-ready release
- [ ] Comprehensive test suite
- [ ] Performance optimizations
- [ ] Plugin system
- [ ] Configuration file support (YAML/JSON)
- [ ] Script scheduling

---

## Notes

### Breaking Changes
None yet - this is the initial release.

### Deprecations
None yet.

### Security
- Scripts are executed with the same permissions as the CLI
- No input sanitization beyond basic path validation
- Users should only run trusted scripts

---

For detailed information about any version, see the git commit history or GitHub releases.
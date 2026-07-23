# HostApp Configuration

This directory contains runtime configuration files for HostApp that are mounted into the frontend container at deployment time.

## Files

### theme-config.json
Theme configuration file documenting the current Look & Feel tokens used in the compiled CSS.

**Purpose:**
- Reference for remote module developers to understand framework CSS classes
- Documentation of theme tokens (colors, spacing, typography, shadows)
- Reference for deployment-time L&F customization planning

**Location in container:** `/usr/share/nginx/html/config/theme-config.json`

**Important Limitations:**
- Tailwind CSS is compiled at build time
- Changes to this file do **not** affect the running application without a frontend rebuild
- This file serves as documentation and reference, not as a runtime CSS modifier
- The frontend bundle contains compiled CSS, not source

**For Runtime Theming:**
To enable actual runtime L&F customization without rebuild, consider:
1. **CSS Variables approach:** Use Tailwind's CSS variable support for theming
2. **External CSS file:** Extract theme CSS to a separate file loaded at runtime
3. **CSS-in-JS or runtime CSS framework:** Switch to a framework that supports runtime styling

## Framework CSS Classes Reference

For a comprehensive reference of all framework CSS classes used in host_app UI components, see:
`modules/host_app/frontend/SPECS/framework-css-classes-reference.md`

This document provides:
- Complete list of `hostapp:` prefixed CSS classes
- Component-specific class combinations
- Usage guidelines for remote module developers
- Override patterns using module-specific prefixes

## Remote Module Development

Remote modules should:
1. Use their own CSS prefix (e.g., `template:` for module_template)
2. Reference framework CSS classes from the reference documentation
3. Override framework classes using module prefix for customizations
4. Never mutate global selectors (`html`, `body`, universal `*`)
5. Keep module-specific L&F customizations scoped to the module root

## Docker Compose Mount

The config directory is mounted in `docker-compose.yml`:
```yaml
volumes:
  - ./config:/usr/share/nginx/html/config:ro
```

This makes all files in this directory available at runtime in the frontend container at `/usr/share/nginx/html/config/`.

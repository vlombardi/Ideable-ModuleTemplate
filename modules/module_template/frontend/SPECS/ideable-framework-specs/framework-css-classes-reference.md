# Framework CSS Classes Reference

This document provides a comprehensive reference of the framework CSS classes used in host_app UI components. Remote module developers should reference these classes to ensure consistent Look & Feel (L&F) across all modules.

## Important Notes

- All framework CSS classes use the `hostapp:` prefix (e.g., `hostapp:bg-primary`)
- Remote modules should use their own prefix (e.g., `template:` for module_template)
- To override framework classes, create a new class with the same name but use a more specific selector by prefixing with the module's CSS prefix
- The actual CSS definitions are provided by host_app at runtime

## Color Tokens

### Semantic Colors
- `hostapp:bg-primary` - Primary action color (default for main buttons)
- `hostapp:text-primary-foreground` - Text color on primary background
- `hostapp:bg-destructive` - Destructive action color (delete, danger)
- `hostapp:text-destructive-foreground` - Text color on destructive background
- `hostapp:bg-secondary` - Secondary action color
- `hostapp:text-secondary-foreground` - Text color on secondary background
- `hostapp:bg-accent` - Accent/hover color
- `hostapp:text-accent-foreground` - Text color on accent background
- `hostapp:bg-muted` - Muted/disabled color
- `hostapp:text-muted-foreground` - Muted text color
- `hostapp:bg-background` - Background color
- `hostapp:bg-card` - Card background color
- `hostapp:text-card-foreground` - Text color on card background
- `hostapp:bg-popover` - Popover/dropdown background color
- `hostapp:text-popover-foreground` - Text color on popover background
- `hostapp:border-input` - Input border color

### Border & Ring
- `hostapp:border-border` - Default border color
- `hostapp:ring-ring` - Focus ring color
- `hostapp:ring-offset-background` - Ring offset background color

## Typography

### Font Sizes
- `hostapp:text-xs` - Extra small text
- `hostapp:text-sm` - Small text (default for form labels, descriptions)
- `hostapp:text-base` - Base text size
- `hostapp:text-lg` - Large text
- `hostapp:text-xl` - Extra large text
- `hostapp:text-2xl` - 2x large text (card titles)
- `hostapp:text-3xl` - 3x large text (page headings)
- `hostapp:text-4xl` - 4x large text (hero headings)

### Font Weights
- `hostapp:font-medium` - Medium weight (default for buttons, labels)
- `hostapp:font-semibold` - Semibold weight (headings, emphasis)
- `hostapp:font-bold` - Bold weight (strong emphasis)

### Text Alignment
- `hostapp:text-left` - Left aligned
- `hostapp:text-center` - Center aligned
- `hostapp:text-right` - Right aligned

### Text Decoration
- `hostapp:underline` - Underlined text
- `hostapp:underline-offset-4` - Underline offset for links

### Text Utilities
- `hostapp:tracking-tight` - Tight letter spacing
- `hostapp:leading-none` - No line height
- `hostapp:placeholder:text-muted-foreground` - Placeholder text color

## Spacing

### Padding
- `hostapp:p-1` - 0.25rem padding
- `hostapp:p-2` - 0.5rem padding
- `hostapp:p-4` - 1rem padding
- `hostapp:p-6` - 1.5rem padding (card padding)
- `hostapp:px-3` - Horizontal 0.75rem padding
- `hostapp:px-4` - Horizontal 1rem padding
- `hostapp:px-8` - Horizontal 2rem padding
- `hostapp:py-1` - Vertical 0.25rem padding
- `hostapp:py-1.5` - Vertical 0.375rem padding
- `hostapp:py-2` - Vertical 0.5rem padding
- `hostapp:pt-0` - No top padding

### Margin
- `hostapp:ml-4` - Left 1rem margin (nested indentation)
- `hostapp:mt-1` - Top 0.25rem margin
- `hostapp:mt-2` - Top 0.5rem margin
- `hostapp:space-y-1` - Vertical space between children (0.25rem)
- `hostapp:space-y-1.5` - Vertical space between children (0.375rem)
- `hostapp:space-y-4` - Vertical space between children (1rem)
- `hostapp:space-y-6` - Vertical space between children (1.5rem)
- `hostapp:space-x-2` - Horizontal space between children (0.5rem)

## Layout

### Display
- `hostapp:flex` - Flexbox container
- `hostapp:inline-flex` - Inline flexbox container
- `hostapp:grid` - Grid container
- `hostapp:block` - Block display
- `hostapp:hidden` - Hidden

### Flexbox
- `hostapp:flex-1` - Flex grow/shrink basis
- `hostapp:flex-col` - Column direction
- `hostapp:flex-col-reverse` - Column reverse direction
- `hostapp:flex-row` - Row direction
- `hostapp:flex-wrap` - Allow wrapping
- `hostapp:items-center` - Center items vertically
- `hostapp:items-start` - Start items vertically
- `hostapp:justify-center` - Center items horizontally
- `hostapp:justify-between` - Space between items
- `hostapp:justify-end` - End items horizontally
- `hostapp:gap-2` - Gap between flex/grid items (0.5rem)
- `hostapp:gap-3` - Gap between flex/grid items (0.75rem)
- `hostapp:gap-4` - Gap between flex/grid items (1rem)

### Grid
- `hostapp:grid-cols-2` - 2 columns
- `hostapp:md:grid-cols-2` - 2 columns on medium screens and up

### Positioning
- `hostapp:relative` - Relative positioning
- `hostapp:absolute` - Absolute positioning
- `hostapp:fixed` - Fixed positioning
- `hostapp:inset-0` - All sides 0
- `hostapp:left-[50%]` - Left 50%
- `hostapp:top-[50%]` - Top 50%
- `hostapp:right-4` - Right 1rem
- `hostapp:top-4` - Top 1rem
- `hostapp:z-50` - Z-index 50 (modals, dropdowns)

## Sizing

### Width
- `hostapp:w-full` - Full width
- `hostapp:w-4` - 1rem width
- `hostapp:w-10` - 2.5rem width
- `hostapp:max-w-lg` - Max width 32rem
- `hostapp:max-w-[425px]` - Max width 425px
- `hostapp:min-w-[8rem]` - Min width 8rem
- `hostapp:min-w-[var(--radix-select-trigger-width)]` - Min width from CSS variable

### Height
- `hostapp:h-4` - 1rem height
- `hostapp:h-8` - 2rem height
- `hostapp:h-9` - 2.25rem height
- `hostapp:h-10` - 2.5rem height (default button/input height)
- `hostapp:h-11` - 2.75rem height
- `hostapp:h-12` - 3rem height
- `hostapp:h-px` - 1px height
- `hostapp:max-h-96` - Max height 24rem
- `hostapp:max-h-[calc(100vh-2rem)]` - Max height with viewport calculation

## Borders & Shapes

### Border Radius
- `hostapp:rounded-md` - Medium border radius (default for buttons, inputs)
- `hostapp:rounded-lg` - Large border radius (cards, dialogs)
- `hostapp:rounded-sm` - Small border radius (select items)
- `hostapp:rounded-full` - Full border radius

### Borders
- `hostapp:border` - Default border
- `hostapp:border-input` - Input border color
- `hostapp:border-t` - Top border
- `hostapp:border-b` - Bottom border
- `hostapp:border-r` - Right border

## Effects

### Shadows
- `hostapp:shadow-sm` - Small shadow (cards)
- `hostapp:shadow-md` - Medium shadow (dropdowns, popovers)
- `hostapp:shadow-lg` - Large shadow (dialogs)

### Opacity
- `hostapp:opacity-50` - 50% opacity
- `hostapp:opacity-60` - 60% opacity
- `hostapp:opacity-70` - 70% opacity

### Transitions
- `hostapp:transition-colors` - Color transitions
- `hostapp:transition-opacity` - Opacity transitions
- `hostapp:transition-all` - All property transitions
- `hostapp:duration-200` - 200ms duration

### Transforms
- `hostapp:translate-x-[-50%]` - Translate X -50%
- `hostapp:translate-y-[-50%]` - Translate Y -50%
- `hostapp:translate-x-1` - Translate X 0.25rem
- `hostapp:translate-y-1` - Translate Y 0.25rem

## Interactive States

### Focus
- `hostapp:focus-visible:outline-none` - Remove outline on focus
- `hostapp:focus-visible:ring-2` - 2px ring on focus
- `hostapp:focus-visible:ring-ring` - Ring color on focus
- `hostapp:focus-visible:ring-offset-2` - 2px ring offset on focus
- `hostapp:focus:outline-none` - Remove outline on focus
- `hostapp:focus:ring-2` - 2px ring on focus
- `hostapp:focus:ring-ring` - Ring color on focus
- `hostapp:focus:ring-offset-2` - 2px ring offset on focus

### Hover
- `hostapp:hover:bg-accent` - Accent background on hover
- `hostapp:hover:bg-primary/90` - 90% primary on hover
- `hostapp:hover:bg-destructive/90` - 90% destructive on hover
- `hostapp:hover:bg-secondary/80` - 80% secondary on hover
- `hostapp:hover:text-accent-foreground` - Accent foreground text on hover
- `hostapp:hover:opacity-100` - Full opacity on hover
- `hostapp:hover:underline` - Underline on hover

### Disabled
- `hostapp:disabled:pointer-events-none` - No pointer events when disabled
- `hostapp:disabled:opacity-50` - 50% opacity when disabled
- `hostapp:disabled:cursor-not-allowed` - Not allowed cursor when disabled
- `hostapp:data-[disabled]:pointer-events-none` - No pointer events for disabled data attribute
- `hostapp:data-[disabled]:opacity-50` - 50% opacity for disabled data attribute

### Active State
- `hostapp:data-[state=active]:bg-background` - Background when active
- `hostapp:data-[state=active]:text-foreground` - Foreground text when active
- `hostapp:data-[state=active]:shadow-sm` - Shadow when active
- `hostapp:data-[state=open]:animate-in` - Animate in when open
- `hostapp:data-[state=open]:fade-in-0` - Fade in when open
- `hostapp:data-[state=open]:zoom-in-95` - Zoom in when open
- `hostapp:data-[state=open]:bg-accent` - Accent background when open
- `hostapp:data-[state=open]:text-muted-foreground` - Muted text when open

## Animations

### Animation States
- `hostapp:animate-in` - Animate in
- `hostapp:animate-out` - Animate out
- `hostapp:fade-in-0` - Fade in from 0
- `hostapp:fade-out-0` - Fade out to 0
- `hostapp:zoom-in-95` - Zoom in to 95%
- `hostapp:zoom-out-95` - Zoom out to 95%
- `hostapp:slide-in-from-top-2` - Slide in from top 0.5rem
- `hostapp:slide-in-from-bottom-2` - Slide in from bottom 0.5rem
- `hostapp:slide-in-from-left-1/2` - Slide in from left 50%
- `hostapp:slide-in-from-right-2` - Slide in from right 0.5rem
- `hostapp:slide-out-to-left-1/2` - Slide out to left 50%
- `hostapp:slide-out-to-top-[48%]` - Slide out to top 48%

## Accessibility

### Screen Reader
- `hostapp:sr-only` - Screen reader only (visually hidden)

### Focus Management
- `hostapp:focus-visible:outline-none` - Remove default outline
- `hostapp:focus-visible:ring-2` - Add custom focus ring

## Component-Specific Classes

### Button
Base: `hostapp:inline-flex hostapp:items-center hostapp:justify-center hostapp:whitespace-nowrap hostapp:rounded-md hostapp:text-sm hostapp:font-medium hostapp:ring-offset-background hostapp:transition-colors hostapp:focus-visible:outline-none hostapp:focus-visible:ring-2 hostapp:focus-visible:ring-ring hostapp:focus-visible:ring-offset-2 hostapp:disabled:pointer-events-none hostapp:disabled:opacity-50`

Variants:
- `default`: `hostapp:bg-primary hostapp:text-primary-foreground hostapp:hover:bg-primary/90`
- `destructive`: `hostapp:bg-destructive hostapp:text-destructive-foreground hostapp:hover:bg-destructive/90`
- `outline`: `hostapp:border hostapp:border-input hostapp:bg-background hostapp:hover:bg-accent hostapp:hover:text-accent-foreground`
- `secondary`: `hostapp:bg-secondary hostapp:text-secondary-foreground hostapp:hover:bg-secondary/80`
- `ghost`: `hostapp:hover:bg-accent hostapp:hover:text-accent-foreground`
- `link`: `hostapp:text-primary hostapp:underline-offset-4 hostapp:hover:underline`

Sizes:
- `default`: `hostapp:h-10 hostapp:px-4 hostapp:py-2`
- `sm`: `hostapp:h-9 hostapp:rounded-md hostapp:px-3`
- `lg`: `hostapp:h-11 hostapp:rounded-md hostapp:px-8`
- `icon`: `hostapp:h-10 hostapp:w-10`

### Input
Base: `hostapp:flex hostapp:h-10 hostapp:w-full hostapp:rounded-md hostapp:border hostapp:border-input hostapp:bg-background hostapp:px-3 hostapp:py-2 hostapp:text-sm hostapp:ring-offset-background hostapp:file:border-0 hostapp:file:bg-transparent hostapp:file:text-sm hostapp:file:font-medium hostapp:placeholder:text-muted-foreground hostapp:focus-visible:outline-none hostapp:focus-visible:ring-2 hostapp:focus-visible:ring-ring hostapp:focus-visible:ring-offset-2 hostapp:disabled:cursor-not-allowed hostapp:disabled:opacity-50`

### Card
- `Card`: `hostapp:rounded-lg hostapp:border hostapp:bg-card hostapp:text-card-foreground hostapp:shadow-sm`
- `CardHeader`: `hostapp:flex hostapp:flex-col hostapp:space-y-1.5 hostapp:p-6`
- `CardTitle`: `hostapp:text-2xl hostapp:font-semibold hostapp:leading-none hostapp:tracking-tight`
- `CardDescription`: `hostapp:text-sm hostapp:text-muted-foreground`
- `CardContent`: `hostapp:p-6 hostapp:pt-0`
- `CardFooter`: `hostapp:flex hostapp:items-center hostapp:p-6 hostapp:pt-0`

### Dialog
- `DialogOverlay`: `hostapp:fixed hostapp:inset-0 hostapp:z-50 hostapp:bg-black/80 hostapp:data-[state=open]:animate-in hostapp:data-[state=closed]:animate-out hostapp:data-[state=closed]:fade-out-0 hostapp:data-[state=open]:fade-in-0`
- `DialogContent`: `hostapp:fixed hostapp:left-[50%] hostapp:top-[50%] hostapp:z-50 hostapp:grid hostapp:w-full hostapp:max-w-lg hostapp:max-h-[calc(100vh-2rem)] hostapp:overflow-y-auto hostapp:translate-x-[-50%] hostapp:translate-y-[-50%] hostapp:gap-4 hostapp:border hostapp:bg-white hostapp:p-6 hostapp:shadow-lg hostapp:duration-200 hostapp:data-[state=open]:animate-in hostapp:data-[state=closed]:animate-out hostapp:data-[state=closed]:fade-out-0 hostapp:data-[state=open]:fade-in-0 hostapp:data-[state=closed]:zoom-out-95 hostapp:data-[state=open]:zoom-in-95 hostapp:data-[state=closed]:slide-out-to-left-1/2 hostapp:data-[state=closed]:slide-out-to-top-[48%] hostapp:data-[state=open]:slide-in-from-left-1/2 hostapp:data-[state=open]:slide-in-from-top-[48%] hostapp:sm:rounded-lg`
- `DialogTitle`: `hostapp:text-lg hostapp:font-semibold hostapp:leading-none hostapp:tracking-tight`
- `DialogDescription`: `hostapp:text-sm hostapp:text-muted-foreground`

### Select
- `SelectTrigger`: `hostapp:flex hostapp:h-10 hostapp:w-full hostapp:items-center hostapp:justify-between hostapp:rounded-md hostapp:border hostapp:border-input hostapp:bg-background hostapp:px-3 hostapp:py-2 hostapp:text-sm hostapp:ring-offset-background hostapp:placeholder:text-muted-foreground hostapp:focus:outline-none hostapp:focus:ring-2 hostapp:focus:ring-ring hostapp:focus:ring-offset-2 hostapp:disabled:cursor-not-allowed hostapp:disabled:opacity-50 hostapp:[&>span]:line-clamp-1`
- `SelectContent`: `hostapp:relative hostapp:z-50 hostapp:max-h-96 hostapp:min-w-[8rem] hostapp:overflow-hidden hostapp:rounded-md hostapp:border hostapp:bg-popover hostapp:text-popover-foreground hostapp:shadow-md hostapp:data-[state=open]:animate-in hostapp:data-[state=closed]:animate-out hostapp:data-[state=closed]:fade-out-0 hostapp:data-[state=open]:fade-in-0 hostapp:data-[state=closed]:zoom-out-95 hostapp:data-[state=open]:zoom-in-95 hostapp:data-[side=bottom]:slide-in-from-top-2 hostapp:data-[side=left]:slide-in-from-right-2 hostapp:data-[side=right]:slide-in-from-left-2 hostapp:data-[side=top]:slide-in-from-bottom-2`
- `SelectItem`: `hostapp:relative hostapp:flex hostapp:w-full hostapp:cursor-default hostapp:select-none hostapp:items-center hostapp:rounded-sm hostapp:py-1.5 hostapp:pl-8 hostapp:pr-2 hostapp:text-sm hostapp:outline-none hostapp:focus:bg-accent hostapp:focus:text-accent-foreground hostapp:data-[disabled]:pointer-events-none hostapp:data-[disabled]:opacity-50`
- `SelectSeparator`: `hostapp:-mx-1 hostapp:my-1 hostapp:h-px hostapp:bg-muted`

### Tabs
- `TabsList`: `hostapp:inline-flex hostapp:h-10 hostapp:items-center hostapp:justify-center hostapp:rounded-md hostapp:bg-muted hostapp:p-1 hostapp:text-muted-foreground`
- `TabsTrigger`: `hostapp:inline-flex hostapp:items-center hostapp:justify-center hostapp:whitespace-nowrap hostapp:rounded-sm hostapp:px-3 hostapp:py-1.5 hostapp:text-sm hostapp:font-medium hostapp:ring-offset-background hostapp:transition-all hostapp:focus-visible:outline-none hostapp:focus-visible:ring-2 hostapp:focus-visible:ring-ring hostapp:focus-visible:ring-offset-2 hostapp:disabled:pointer-events-none hostapp:disabled:opacity-50 hostapp:data-[state=active]:bg-background hostapp:data-[state=active]:text-foreground hostapp:data-[state=active]:shadow-sm`
- `TabsContent`: `hostapp:mt-2 hostapp:ring-offset-background hostapp:focus-visible:outline-none hostapp:focus-visible:ring-2 hostapp:focus-visible:ring-ring hostapp:focus-visible:ring-offset-2`

### Tooltip
- `TooltipContent`: `hostapp:z-50 hostapp:overflow-hidden hostapp:rounded-md hostapp:border hostapp:bg-popover hostapp:px-3 hostapp:py-1.5 hostapp:text-sm hostapp:text-popover-foreground hostapp:shadow-md hostapp:animate-in hostapp:fade-in-0 hostapp:zoom-in-95 hostapp:data-[state=closed]:animate-out hostapp:data-[state=closed]:fade-out-0 hostapp:data-[state=closed]:zoom-out-95 hostapp:data-[side=bottom]:slide-in-from-top-2 hostapp:data-[side=left]:slide-in-from-right-2 hostapp:data-[side=right]:slide-in-from-left-2 hostapp:data-[side=top]:slide-in-from-bottom-2`

## Usage Guidelines for Remote Modules

1. **Reference framework classes**: Use the classes listed above to match host_app L&F
2. **Override with module prefix**: To customize, create a new class with the same name but prefix with your module's CSS prefix (e.g., `.template:bg-primary`)
3. **Use descendant selectors**: For more specific overrides, use descendant selectors like `.template-scope .hostapp:bg-primary`
4. **Don't mutate global selectors**: Never override `html`, `body`, or universal `*` selectors
5. **Scope customizations**: Keep module-specific L&F customizations scoped to the module root only

## Important Limitations

- **Tailwind CSS is compiled at build time**: The frontend bundle contains compiled CSS, not source
- **Runtime configuration file cannot change compiled CSS**: A config file in `hostapp/config` cannot modify the actual CSS rules in the compiled bundle
- **For runtime theming**: Consider using CSS variables or a separate runtime CSS file approach
- **Current config file approach**: The config file serves as documentation and reference, not as a runtime CSS modifier

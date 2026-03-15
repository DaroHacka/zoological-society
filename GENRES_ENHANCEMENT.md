# Genre Organization Enhancement

## Overview

The Genres feature has been enhanced with new organization capabilities, making labels more manageable as your collection grows and becomes more rich and nuanced.

## New Features

### 1. Highlight Important Labels

You can now highlight labels that are more important or frequently used. Highlighted labels appear with a soft glow effect, making them instantly recognizable while maintaining their alphabetical position.

**How to use:**
- Click the gear icon (⚙️) next to "📂 Genres" to enter edit mode
- Click on any label to toggle its highlight status
- Highlighted labels show a subtle glow effect in the sidebar

### 2. Custom Groups

Create personalized groups to organize related labels together, regardless of their initial letter.

**How to use:**
- In the edit panel, click "+ Create Group"
- Give your group a name (e.g., "Favorites", "RPG Games", "Indie Gems")
- Select which labels to include in the group
- Groups appear at the top of the genres list, before the letter sections

**Group management:**
- Click ✏️ to rename a group
- Click 📝 to edit which labels belong to the group
- Click 🗑️ to delete a group (labels return to the general list)

### 3. Collapsible Letter Sections

Labels are now organized by their first letter (A-Z) and numbers (#). Each letter section can be expanded or collapsed to show/hide all labels within that letter.

**How it works:**
- When collapsed: Shows highlighted labels first, then regular labels up to the configured count
- When expanded: Shows all labels in alphabetical order
- Click on a letter to toggle its expansion state
- The total count is shown next to each letter (e.g., "A 14")

### 4. Configurable Collapsed Count

Control how many labels appear when a letter section is collapsed (1-10).

**How to use:**
- In the edit panel, use the number input to set how many labels to show when collapsed
- Default is 5 labels

## Console Deletion Protection

As an additional safety measure, deleting a console now requires typing "123" to confirm, preventing accidental deletion of your entire game collection.

## Technical Details

- All organization preferences are stored in the browser's localStorage
- Settings are saved per-console, so each console can have its own unique organization
- The gear icon only appears when you're inside a specific console with at least one genre

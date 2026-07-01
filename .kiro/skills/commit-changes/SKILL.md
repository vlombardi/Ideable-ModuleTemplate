---
name: commit-changes
description: create a commit for each set of changes that belong to a consistent group of changes. 
category: development
displayName: Commit changes
---

Analyze all the changes from the last commit and create a commit for each group of changes that:
- describe a consistent set of changes (e.g., all modified/added/deleted files that implement a new feature or solve a specific bug)
- can be summarized with a short unique commit name

For each set of changes:
- define the files to add to the commit
- create a commit message composed as follows:
  - "New feature" or "Bugfix", or "Improvement", followed by a short title, e.g., "New button 'Add item' in Items page"
  - a message describing the change using:
    - one line if it is trivial
    - minimun 3, maximum 10 lines if it is not trivial 
- commit and print the files list and the commit message for user convenience
- tell the user to push the change, to change the message or to roll-back 
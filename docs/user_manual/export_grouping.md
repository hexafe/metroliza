# Export Grouping

## What grouping is for

The **Data grouping** dialog lets you assign exported parts into named groups.

Open it from the Export dialog by clicking **Edit...** next to **Grouping**.

Use grouping when you want to:

- compare named groups in the export,
- prepare data for the **Group Analysis worksheet**, or
- organize a mixed population into smaller logical sets.

Grouping affects the export workflow. It does not replace filtering.

## Understanding the four panes

The dialog is built around four main panes.

### REFERENCE

This pane lists references in the current export scope.

Use it to focus the **PART #** pane on one reference at a time.

Double-clicking a reference is also a shortcut into group creation.

### PART #

This pane lists the available parts/rows for the selected reference.

Rows are shown with identifying details so you can tell items apart.

You can multi-select parts here.

Double-clicking a part is a shortcut into group creation.

### GROUPS

This pane lists existing groups.

A default group named **POPULATION** always exists.

- **POPULATION** means unassigned/default rows.
- User-created groups are color-coded.
- The list also shows a count, such as `Group A (n=12)`.

Double-clicking a group opens the rename flow.

### PART IN SELECTED GROUP

This pane shows the parts that belong to the currently selected group.

Use it to review or remove members from a group.

## Understanding POPULATION

**POPULATION** is the default/unassigned group.

If a part is not assigned to one of your custom groups, it belongs to **POPULATION**.

If you remove a part from a custom group, it goes back to **POPULATION**.

If you delete a custom group, its parts also go back to **POPULATION**.

## Creating groups

### Create a new group from selected parts

1. In **PART #**, select one or more parts.
2. Click **Create/add to group**.
3. Enter the group name.
4. Confirm.

If the group name is new, a new group is created.

If the group name already exists, the selected parts are added to that existing group.

### Create a group from the selected reference

If no parts are selected, **Create/add to group** can still work from the currently selected reference.

In that case, the dialog uses the selected reference’s rows as the target set.

This is helpful when you want to group an entire reference quickly.

### Color-coded groups

Custom groups are automatically color-coded so they are easier to distinguish in the dialog.

**POPULATION** keeps the default background color.

## Renaming, removing, and deleting

### Rename selected group

1. Select a group in **GROUPS**.
2. Click **Rename selected group**.
3. Enter the new name.

You can also double-click the group to open the rename flow.

### Remove from selected group

1. Select a custom group.
2. In **PART IN SELECTED GROUP**, select the part or parts you want to remove.
3. Click **Remove from selected group**.

The removed items return to **POPULATION**.

### Delete selected group

1. Select a custom group in **GROUPS**.
2. Click **Delete selected group**.
3. Confirm deletion.

Deleting the group does not delete the parts. It only removes that custom group assignment and returns its members to **POPULATION**.

You cannot delete **POPULATION**.

## Saving grouping into Export

The bottom of the dialog has two important actions:

### Use grouping

This saves the current grouping setup back into the Export dialog.

When you click **Use grouping**:

- the grouping dialog closes,
- Export stores the current grouping data,
- the Export dialog marks grouping as applied.

Important behavior: if grouping is applied while **Group analysis** was **Off**, Export automatically switches it to **Standard** so grouped analysis can be included.

### Do not use grouping

This closes the dialog and tells Export not to use grouping.

If you choose this, Export clears the saved grouping context and marks grouping as not applied.

## How grouping affects exported reports

Grouping matters because it changes how the export can compare data.

In practical terms, grouping lets the workbook compare named groups rather than treating everything as one undivided population.

This is especially important for the **Group Analysis worksheet**.

For help reading that worksheet after export, see [Group Analysis worksheet manual](group_analysis/user_manual.md).

## Keyboard and double-click shortcuts

The dialog includes several shortcuts.

### Double-click shortcuts

- Double-click a **REFERENCE** item to start group creation with that reference name prefilled.
- Double-click a **PART #** item to start group creation.
- Double-click a **GROUPS** item to rename that group.

### Keyboard shortcuts

- Press **Enter** while the **REFERENCE** list has focus to start group creation for the selected reference.
- Press **Delete** or **Backspace** in **PART #** to remove the selected parts from their current custom group and return them to **POPULATION**.
- Press **Delete** or **Backspace** in **PART IN SELECTED GROUP** to remove those selected items from the current group.
- Press **Delete** or **Backspace** in **GROUPS** to delete the selected custom group.

The result depends on which pane currently has focus, so make sure the correct list is active before using Delete.

## Common mistakes

### I expected filtering, but grouping did not remove rows

That is expected.

Grouping assigns rows to groups. It does not filter rows out of the export. Use [Export filtering](export_filtering.md) if you need to narrow the data itself.

### I removed a part and thought it was deleted

Removing from a group sends it back to **POPULATION**. It does not delete the part from the export data.

### I created grouping but do not see it in Export

Make sure you clicked **Use grouping**. If you close the dialog or click **Do not use grouping**, Export will not use the grouping setup.

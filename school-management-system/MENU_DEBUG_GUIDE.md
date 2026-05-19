# MENU SIDEBAR DEBUGGING GUIDE

If you're not seeing the menu items (Class, Settings, Events, etc.) on the left sidebar after login, follow these steps:

## Step 1: Open Browser Developer Console

1. Press **F12** on your keyboard to open Developer Tools
2. Click on the **Console** tab
3. You should see a white text input area at the bottom

## Step 2: Perform Login

1. Go to http://127.0.0.1:8000
2. Enter username: `admin`
3. Enter password: `admin`
4. Click "Sign In" button

## Step 3: Check Console for Debug Messages

After you log in, look for messages in the Console that start with `[DEBUG]`. These will tell us what's happening:

Examples of what you should see:
```
[DEBUG] DOMContentLoaded: calling /auth/me/
[DEBUG] DOMContentLoaded: /auth/me/ returned {id: 1, username: "admin", ...}
[DEBUG] === doLogin() STARTING ===
[DEBUG] doLogin() - calling /auth/login/...
[DEBUG] === enterApp() STARTING ===
[DEBUG] enterApp() - currentUser: {id: 1, username: "admin", ...}
[DEBUG] enterApp() - currentUser.profile.role: superadmin
[DEBUG] buildSidebar(): role= superadmin
[DEBUG] buildSidebar() completed successfully
```

## Step 4: Run the Debug Sidebar Function

In the Console, type this command and press Enter:

```javascript
debugSidebar()
```

This will show you detailed information about the sidebar status. Look for:
- `currentUser.profile.role: superadmin` - confirms role is correct
- `sb-nav-content element exists: true` - confirms sidebar HTML element exists
- `sb-nav-content innerHTML length:` - should be more than 100 characters (not 0)
- `sb-nav-content children count:` - should be many items (not 0)

## Step 5: Check if Menu is Hidden by CSS

In the Console, run this:

```javascript
document.getElementById('sidebar').style.display
```

It should show `flex` or similar, NOT `none`.

## Step 6: Force Sidebar to Show (Temporary Fix)

If the sidebar exists but is hidden, type this in Console:

```javascript
document.getElementById('sidebar').style.display = 'flex'
document.getElementById('sb-nav-content').style.display = 'flex'
document.getElementById('sb-nav-content').style.visibility = 'visible'
```

If the menu appears after running these commands, then it's a CSS/display issue.

## Step 7: Force Rebuild Menu

Type this in Console:

```javascript
buildSidebar()
```

This manually rebuilds the sidebar. If items appear after this, the menu might not be rebuilding on login.

## Step 8: Share Console Output

If the sidebar still doesn't appear, right-click in the Console and select "Save as" to save the console log. Share these messages so I can see what's actually happening:

1. Look for any RED error messages (these are important!)
2. Look for all messages starting with `[DEBUG]`
3. Look for any messages starting with `[ERROR]` or `[WARNING]`

## What Each Debug Message Means

| Message | What it means |
|---------|--------------|
| `[DEBUG] buildSidebar(): role= superadmin` | Role is correct ✓ |
| `[ERROR] buildSidebar() threw exception:` | Something went wrong in buildSidebar() |
| `[ERROR] sb-nav-content element NOT FOUND!` | The sidebar HTML container doesn't exist |
| `sb-nav-content innerHTML length: 0` | Menu HTML wasn't generated |
| `sb-nav-content children count: 0` | No menu items were created |

## Quick Browser Cache Fix

If you've logged in before, the old app.js might be cached:

1. Press **Ctrl+Shift+Delete** (or Cmd+Shift+Delete on Mac)
2. Select "Cached images and files"
3. Click "Clear"
4. Refresh the page (F5)
5. Try logging in again

---

**After you try these steps, please share:**
1. Any RED error messages from the console
2. The output of `debugSidebar()`
3. What you see on the page (is sidebar visible? is it empty? etc.)

This will help identify exactly what's happening with the menu.

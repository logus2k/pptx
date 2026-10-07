// Slides: copied verbatim from Cortex (static/js/shell/MenuBar.js).
export class MenuBar {

    constructor(selector) {

        this.root = document.querySelector(selector)
        this.menus = []
        this.commands = new Map()
        this.context = {}
        this.shortcutMap = {}
        this.itemBindings = []

        this.root.classList.add("menubar")

        this.installKeyboard()

        document.addEventListener("click", () => this.closeAll())

    }

    registerCommand(id, handler) {
        this.commands.set(id, handler)
    }

    executeCommand(id, args) {

        const handler = this.commands.get(id)

        if (handler) {
            handler(args)
            this.refresh()
        } else {
            console.warn(`Command not registered: ${id}`)
        }

    }

    setContext(key, value) {
        this.context[key] = value
    }

    getContext(key) {
        return this.context[key]
    }

    async load(url) {

        const res = await fetch(url)
        this.model = await res.json()
        this.render()
        return this

    }

    render() {

        this.root.innerHTML = ""
        this.menus = []
        this.itemBindings = []
        this.shortcutMap = {}

        this.model.forEach((menu, i) => {

            const menuEl = document.createElement("div")
            menuEl.className = "menu"

            const btn = document.createElement("div")
            btn.className = "menu-btn"
            btn.textContent = menu.label

            btn.addEventListener("click", (e) => {

                e.stopPropagation()
                this.toggleMenu(i)

            })

            btn.addEventListener("mouseenter", () => {

                if (this.menus.some(m => m.classList.contains("open"))) {
                    this.closeAll()
                    menuEl.classList.add("open")
                }

            })

            const dropdown = this.createMenu(menu.items)

            menuEl.appendChild(btn)
            menuEl.appendChild(dropdown)

            this.root.appendChild(menuEl)

            this.menus.push(menuEl)

        })

    }

    createMenu(items) {

        const container = document.createElement("div")
        container.className = "dropdown"

        items.forEach(item => {

            if (item.type === "separator") {

                const sep = document.createElement("div")
                sep.className = "separator"
                container.appendChild(sep)
                return

            }

            if (item.type === "radio-group") {

                const radioItems = item.items
                radioItems.forEach(r => {

                    r._radioGroup = radioItems
                    container.appendChild(this.createItem(r, "radio"))

                })

                return

            }

            container.appendChild(this.createItem(item))

        })

        return container

    }

    createItem(item, mode) {

        const el = document.createElement("div")
        el.className = "menu-item"

        // Evaluate enabled condition
        if (item.enabled && !this.getContext(item.enabled))
            el.classList.add("disabled")

        // Evaluate visibility condition
        if (item.when && !this.getContext(item.when))
            el.style.display = "none"

        const left = document.createElement("span")

        const check = document.createElement("span")
        check.className = "check"

        if (item.type === "checkbox" && item.checked && this.getContext(item.checked))
            check.textContent = "\u2713"

        if (mode === "radio" && item.checked && this.getContext(item.checked))
            check.textContent = "\u25CF"

        left.appendChild(check)
        left.append(item.label)

        const right = document.createElement("span")

        if (item.shortcut) {

            right.className = "shortcut"
            right.textContent = item.shortcut

            this.shortcutMap[item.shortcut.toLowerCase()] = item

        }

        el.appendChild(left)
        el.appendChild(right)

        if (item.submenu) {

            el.classList.add("has-sub")

            const arrow = document.createElement("span")
            arrow.className = "arrow"
            arrow.textContent = ">"

            right.appendChild(arrow)

            const sub = this.createMenu(item.submenu)
            sub.classList.add("submenu")

            el.appendChild(sub)

            let hideTimeout = null

            el.addEventListener("mouseenter", () => {

                clearTimeout(hideTimeout)

                const itemRect = el.getBoundingClientRect()

                let leftPos = itemRect.width + 3
                let topPos = -3;

                sub.style.display = "block"
                sub.style.left = leftPos + "px"
                sub.style.top = topPos + "px"

                const subRect = sub.getBoundingClientRect()

                if (subRect.right > window.innerWidth) {
                    sub.style.left = (-subRect.width) + "px"
                }

                if (subRect.bottom > window.innerHeight) {
                    sub.style.top = (window.innerHeight - subRect.height - itemRect.top - 5) + "px"
                }

            })

            el.addEventListener("mouseleave", () => {
                hideTimeout = setTimeout(() => {
                    sub.style.display = "none"
                }, 50)
            })

            sub.addEventListener("mouseenter", () => {
                clearTimeout(hideTimeout)
            })

        }

        el.addEventListener("click", (e) => {

            e.stopPropagation()

            if (item.command)
                this.executeCommand(item.command, item.args)

            this.closeAll()

        })

        // Store binding for refresh
        this.itemBindings.push({ el, checkEl: check, item, mode })

        return el

    }

    refresh() {

        this.itemBindings.forEach(({ el, checkEl, item, mode }) => {

            // Update enabled state
            if (item.enabled) {
                if (this.getContext(item.enabled))
                    el.classList.remove("disabled")
                else
                    el.classList.add("disabled")
            }

            // Update visibility
            if (item.when) {
                el.style.display = this.getContext(item.when) ? "" : "none"
            }

            // Update checked state
            if (item.type === "checkbox" && item.checked) {
                // written only when it changes (Cortex): a rewrite replaces the node under a click in progress
                const mark = this.getContext(item.checked) ? "\u2713" : ""
                if (checkEl.textContent !== mark) checkEl.textContent = mark
            }

            if (mode === "radio" && item.checked) {
                const dot = this.getContext(item.checked) ? "\u25CF" : ""
                if (checkEl.textContent !== dot) checkEl.textContent = dot
            }

        })

    }

    toggleMenu(index) {

        const m = this.menus[index]

        const open = m.classList.contains("open")

        this.closeAll()

        if (!open)
            m.classList.add("open")

    }

    closeAll() {

        this.menus.forEach(m => m.classList.remove("open"))

        document
            .querySelectorAll(".submenu")
            .forEach(s => s.style.display = "none")

    }

    _isFocusInEditable() {
        const el = document.activeElement
        if (!el) return false
        const tag = el.tagName
        if (tag === "INPUT" || tag === "TEXTAREA") return true
        if (el.isContentEditable) return true
        // CodeMirror's content surface is contenteditable; the check
        // above usually catches it. As a safety net, also detect the
        // ".cm-content" class that CM6 puts on its editable element.
        if (el.classList && el.classList.contains("cm-content")) return true
        return false
    }

    installKeyboard() {

        document.addEventListener("keydown", (e) => {

            const key = e.key.toLowerCase()

            // Cortex: Escape closes an open menu (it stayed open until a click elsewhere)
            if (key === "escape" && this.menus.some(m => m.classList.contains("open"))) {
                this.closeAll()
                return
            }

            if (e.altKey && this.model) {

                this.model.forEach((m, i) => {

                    if (m.key && m.key.toLowerCase() === key) {

                        e.preventDefault()
                        this.toggleMenu(i)

                    }

                })

            }

            const combo = []

            if (e.ctrlKey) combo.push("ctrl")
            if (e.shiftKey) combo.push("shift")

            combo.push(key)

            const str = combo.join("+")

            const item = this.shortcutMap[str]

            if (item) {

                // Don't steal text-editing shortcuts (Ctrl+Z, Ctrl+Y,
                // Ctrl+C, Ctrl+V, Ctrl+X, Ctrl+A) when focus is inside
                // an editable surface like a CodeMirror cell, an
                // <input>, a <textarea>, or any contenteditable element.
                // The editor's own keymap (e.g. CodeMirror's history)
                // needs to handle them - if we preventDefault() here,
                // the editor never sees the event and undo silently
                // fails (or in noted's case, crashes because
                // NotebookEditor has no public undo() method, only
                // a private cell-structural _undo()).
                //
                // The shortcut is still available via the menu click
                // path for when no editor is focused.
                const isEditingShortcut = (
                    str === "ctrl+z" || str === "ctrl+shift+z" ||
                    str === "ctrl+y" || str === "ctrl+c" ||
                    str === "ctrl+v" || str === "ctrl+x" ||
                    str === "ctrl+a"
                )
                if (isEditingShortcut && this._isFocusInEditable()) {
                    return
                }

                e.preventDefault()

                if (item.command)
                    this.executeCommand(item.command, item.args)

            }

        })

    }

}

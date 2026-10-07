// Slides: copied verbatim from Cortex (static/js/shell/SidebarPanel.js).
/**
 * SidebarPanel - Collapsible/expandable panel between the icon bar and content area.
 * Hosts different views (explorer tree, etc.) selected via the icon bar.
 * Lives in the normal flex flow of #below-bar.
 */

export class SidebarPanel {
    /**
     * @param {object} [callbacks] - { onResize() }
     */
    constructor(callbacks = {}) {
        this._panel = document.getElementById('sidebar-panel');
        this._resizer = document.getElementById('sidebar-resizer');
        this._iconBar = document.getElementById('icon-bar');
        this._contentArea = document.getElementById('content-area');
        this._callbacks = callbacks;
        this._header = null;
        this._tabsEl = null;
        this._contentEl = null;
        this._visible = false;
        this._activeView = null;
        this._savedWidth = null;
        this._views = {};
        this._openViews = new Set(); // tracks all currently open (not just shown) view keys

        this._build();
        this._setupResize();
    }

    _build() {
        this._panel.innerHTML = '';

        // Header — contains tabs
        this._header = document.createElement('div');
        this._header.className = 'sidebar-header';

        this._tabsEl = document.createElement('div');
        this._tabsEl.className = 'sidebar-tabs';
        this._header.appendChild(this._tabsEl);

        this._panel.appendChild(this._header);

        // Title bar — shows the active view's title or a custom titleElement
        this._titleBar = document.createElement('div');
        this._titleBar.className = 'sidebar-title-bar';

        this._titleEl = document.createElement('div');
        this._titleEl.className = 'sidebar-title';
        this._titleBar.appendChild(this._titleEl);

        // Close button (right side)
        this._closeBtn = document.createElement('button');
        this._closeBtn.className = 'sidebar-close-btn';
        this._closeBtn.title = 'Close panel';
        this._closeBtn.innerHTML = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>';   // Cortex: an inline icon in currentColor (noted: Font Awesome, an inline colour)
        this._closeBtn.addEventListener('click', () => {
            if (this._activeView) this.close(this._activeView);
        });
        this._titleBar.appendChild(this._closeBtn);

        this._panel.appendChild(this._titleBar);
        this._activeTitleElement = null;

        // Content area
        this._contentEl = document.createElement('div');
        this._contentEl.className = 'sidebar-content';
        this._panel.appendChild(this._contentEl);
    }

    _setupResize() {
        let startX, startWidth, rafId;

        this._resizer.addEventListener('pointerdown', (e) => {
            if (e.button !== 0) return;
            e.preventDefault();
            this._resizer.setPointerCapture(e.pointerId);
            const wasClosed = !this._visible;
            startX = e.clientX;
            startWidth = this._panel.getBoundingClientRect().width;
            // Fixed reference: the right edge of the icon bar (always visible)
            const baseLeft = this._iconBar.getBoundingClientRect().right;
            rafId = 0;
            this._resizer.classList.add('dragging');
            document.body.classList.add('resizing');
            document.body.style.userSelect = 'none';
            document.body.style.cursor = 'col-resize';
            this._panel.style.transition = 'none';
            // Contain layout during drag to limit reflow scope (on content-area, which holds the iframe)
            this._contentArea.style.contain = 'inline-size layout style';
            // Disable other resizers during drag to prevent cross-capture
            const otherResizer = document.getElementById('notebook-resizer');
            if (otherResizer) otherResizer.style.pointerEvents = 'none';
            // Overlay iframes to prevent them from stealing pointer events
            const iframeOverlay = document.createElement('div');
            iframeOverlay.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;z-index:9999;cursor:col-resize;touch-action:none';
            document.body.appendChild(iframeOverlay);
            // Capture center column width and current resizer margin so we can compensate during drag
            const centerCol = document.getElementById('center-column');
            const startCenterWidth = centerCol ? centerCol.getBoundingClientRect().width : 0;
            const startMargin = wasClosed ? parseFloat(this._resizer.style.marginLeft) || 0 : 0;

            const onPointerMove = (e) => {
                if (rafId) return;
                rafId = requestAnimationFrame(() => {
                    if (wasClosed) {
                        const margin = Math.max(0, Math.min(750, e.clientX - baseLeft));
                        this._resizer.style.marginLeft = margin + 'px';
                        // Compensate center column so right splitter stays fixed
                        if (centerCol) {
                            const dx = margin - (startMargin || 0);
                            const newCenterWidth = Math.max(400, startCenterWidth - dx);
                            centerCol.style.width = newCenterWidth + 'px';
                        }
                    } else {
                        const rawWidth = startWidth + (e.clientX - startX);
                        const newWidth = Math.max(160, Math.min(750, rawWidth));
                        this._panel.style.width = newWidth + 'px';
                        // Compensate center column so right splitter stays fixed
                        if (centerCol) {
                            const dx = newWidth - startWidth;
                            const newCenterWidth = Math.max(400, startCenterWidth - dx);
                            centerCol.style.width = newCenterWidth + 'px';
                        }
                    }
                    rafId = 0;
                });
            };

            const onPointerUp = () => {
                if (rafId) cancelAnimationFrame(rafId);
                this._resizer.classList.remove('dragging');
                document.body.classList.remove('resizing');
                document.body.style.userSelect = '';
                document.body.style.cursor = '';
                this._panel.style.transition = '';
                this._contentArea.style.contain = '';
                // Re-enable other resizers
                const otherResizer = document.getElementById('notebook-resizer');
                if (otherResizer) otherResizer.style.pointerEvents = '';
                // Remove iframe overlay
                if (iframeOverlay.parentNode) iframeOverlay.remove();
                if (wasClosed) {
                    this._savedMargin = this._resizer.style.marginLeft || null;
                } else {
                    this._savedWidth = this._panel.style.width || null;
                }
                this._resizer.removeEventListener('pointermove', onPointerMove);
                this._resizer.removeEventListener('pointerup', onPointerUp);
                this._resizer.removeEventListener('pointercancel', onPointerUp);
                try { this._resizer.releasePointerCapture(e.pointerId); } catch (_) {}
                if (this._callbacks.onResize) this._callbacks.onResize();
            };

            this._resizer.addEventListener('pointermove', onPointerMove);
            this._resizer.addEventListener('pointerup', onPointerUp);
            this._resizer.addEventListener('pointercancel', onPointerUp);
        });
    }

    /**
     * Register a named view that can be shown in the sidebar.
     * @param {string} key - View identifier (e.g. 'projects', 'environments')
     * @param {object} view - { title: string, element: HTMLElement }
     */
    /**
     * Register a named view that can be shown in the sidebar.
     * @param {string} key - View identifier (e.g. 'projects', 'toc')
     * @param {object} view - { tabLabel: string, title: string, element: HTMLElement, onActivate?, onDeactivate? }
     */
    registerView(key, view) {
        this._views[key] = view;
        view.element.style.display = 'none';
        this._contentEl.appendChild(view.element);

        // Create a tab in the header
        const tab = document.createElement('div');
        tab.className = 'sidebar-tab';
        const label = document.createElement('span');
        label.textContent = view.tabLabel || view.title;
        tab.appendChild(label);
        const closeBtn = document.createElement('span');
        closeBtn.className = 'sidebar-tab-close';
        closeBtn.textContent = '\u00d7';
        closeBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            this.close(key);
        });
        tab.appendChild(closeBtn);
        tab.dataset.key = key;
        tab.addEventListener('click', () => this.show(key));
        this._tabsEl.appendChild(tab);
        view._tab = tab;
    }

    /**
     * Show the sidebar with a specific view.
     * @param {string} key - The view key to display
     */
    show(key) {
        const view = this._views[key];
        if (!view) return;
        this._openViews.add(key);

        // Deactivate previous view (keep 'open', only remove 'active')
        if (this._activeView && this._views[this._activeView]) {
            const prev = this._views[this._activeView];
            prev.element.style.display = 'none';
            if (prev._tab) prev._tab.classList.remove('active');
            if (prev.onDeactivate) prev.onDeactivate();
        }

        // Show new view
        this._activeView = key;

        // Restore default title element if previous view had a custom one
        if (this._activeTitleElement) {
            this._titleBar.replaceChild(this._titleEl, this._activeTitleElement);
            this._activeTitleElement = null;
        }

        if (view.titleElement) {
            this._titleBar.replaceChild(view.titleElement, this._titleEl);
            this._activeTitleElement = view.titleElement;
        } else {
            this._titleEl.textContent = view.title;
        }

        view.element.style.display = '';
        if (view._tab) view._tab.classList.add('open', 'active');
        if (view.onActivate) view.onActivate();

        if (!this._visible) {
            this._visible = true;
            if (this._savedWidth) {
                this._panel.style.width = this._savedWidth;
            }
            this._panel.classList.add('sidebar-open');
            this._resizer.classList.add('sidebar-open');
            // Clear any margin set by resizer drag while closed
            this._resizer.style.marginLeft = '';
            this._savedMargin = null;
        }

        if (this._callbacks.onViewChange) this._callbacks.onViewChange(key);
    }

    /**
     * Hide the sidebar entirely.
     */
    hide() {
        // Save current sidebar width as resizer margin to keep content-area position
        const currentWidth = this._panel.getBoundingClientRect().width;
        this._openViews.clear();
        this._visible = false;
        this._panel.classList.remove('sidebar-open');
        this._resizer.classList.remove('sidebar-open');
        // Set resizer margin to maintain content position
        if (currentWidth > 0) {
            this._resizer.style.marginLeft = currentWidth + 'px';
            this._savedMargin = currentWidth + 'px';
        } else if (this._savedMargin) {
            this._resizer.style.marginLeft = this._savedMargin;
        }

        if (this._activeView && this._views[this._activeView]) {
            const prev = this._views[this._activeView];
            prev.element.style.display = 'none';
            if (prev._tab) prev._tab.classList.remove('open', 'active');
            if (prev.onDeactivate) prev.onDeactivate();
        }
        for (const view of Object.values(this._views)) {
            if (view._tab) view._tab.classList.remove('open', 'active');
        }
        this._activeView = null;

        if (this._callbacks.onViewChange) this._callbacks.onViewChange(null);
    }

    /**
     * Close a specific view. If it was the active view, switch to another open view
     * or hide the sidebar if none remain open.
     */
    close(key) {
        this._openViews.delete(key);
        const view = this._views[key];
        if (view?._tab) view._tab.classList.remove('open', 'active');
        if (this._activeView === key) {
            const remaining = [...this._openViews];
            if (remaining.length > 0) {
                this.show(remaining[remaining.length - 1]);
            } else {
                this.hide();
            }
        }
        if (this._callbacks.onViewChange) this._callbacks.onViewChange(this._activeView);
    }

    /**
     * Toggle a view: open it if not open, close it if already open.
     */
    toggle(key) {
        if (this._openViews.has(key)) {
            this.close(key);
        } else {
            this.show(key);
        }
    }

    /**
     * Update a view's title. Refreshes the title bar if that view is active.
     */
    updateViewTitle(key, title) {
        const view = this._views[key];
        if (!view) return;
        view.title = title;
        if (this._activeView === key) {
            this._titleEl.textContent = title;
        }
    }

    get openViews() { return this._openViews; }

    get visible() {
        return this._visible;
    }

    get activeView() {
        return this._activeView;
    }

    get contentEl() {
        return this._contentEl;
    }

    get width() {
        return this._panel.getBoundingClientRect().width;
    }
}

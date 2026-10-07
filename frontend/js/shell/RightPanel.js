// Slides: copied verbatim from Cortex (static/js/shell/RightPanel.js).
/**
 * RightPanel - Tabbed panel for the right side (Assistant, Prompts, etc.)
 * Mirrors the SidebarPanel tab system with matching styling.
 */
export class RightPanel {

    constructor(container) {
        this._container = container;
        this._views = {};
        this._activeView = null;
        this._openViews = new Set();
        this._onClose = null;
        this._build();
    }

    _build() {
        this._container.innerHTML = '';

        // Header — contains tabs
        this._header = document.createElement('div');
        this._header.className = 'right-panel-header';

        this._tabsEl = document.createElement('div');
        this._tabsEl.className = 'right-panel-tabs';
        this._header.appendChild(this._tabsEl);
        this._container.appendChild(this._header);

        // Title bar
        this._titleBar = document.createElement('div');
        this._titleBar.className = 'right-panel-title-bar';
        this._titleEl = document.createElement('div');
        this._titleEl.className = 'right-panel-title';
        this._titleBar.appendChild(this._titleEl);

        // Status label + LED (right-aligned)
        this._statusLabel = document.createElement('span');
        this._statusLabel.className = 'right-panel-status-label';
        this._titleBar.appendChild(this._statusLabel);

        this._statusLed = document.createElement('span');
        this._statusLed.className = 'right-panel-status-led';
        this._titleBar.appendChild(this._statusLed);

        // Custom button slot (views can inject extra buttons here)
        this._customBtnSlot = document.createElement('span');
        this._customBtnSlot.className = 'right-panel-custom-btns';
        this._titleBar.appendChild(this._customBtnSlot);

        // Undock button
        this._undockBtn = document.createElement('button');
        this._undockBtn.className = 'sidebar-close-btn';
        this._undockBtn.title = 'Undock to floating window';
        this._undockBtn.innerHTML = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 4h6v6M20 4l-9 9M18 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4"/></svg>';   // Cortex: an inline icon in currentColor (noted: Font Awesome, an inline colour)
        this._undockBtn.style.display = 'none';
        this._undockBtn.addEventListener('click', () => {
            if (this._onUndock) this._onUndock(this._activeView);
        });
        this._titleBar.appendChild(this._undockBtn);

        // Close button
        this._closeBtn = document.createElement('button');
        this._closeBtn.className = 'sidebar-close-btn';
        this._closeBtn.title = 'Close panel';
        this._closeBtn.innerHTML = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>';   // Cortex: as above
        this._closeBtn.addEventListener('click', () => {
            if (this._activeView) this.close(this._activeView);
        });
        this._titleBar.appendChild(this._closeBtn);

        this._container.appendChild(this._titleBar);

        // Content area
        this._contentEl = document.createElement('div');
        this._contentEl.className = 'right-panel-content';
        this._container.appendChild(this._contentEl);
    }

    registerView(key, view) {
        this._views[key] = view;
        view.element.style.display = 'none';
        this._contentEl.appendChild(view.element);

        const tab = document.createElement('div');
        tab.className = 'right-panel-tab';
        const label = document.createElement('span');
        label.textContent = view.tabLabel || view.title;
        tab.appendChild(label);
        const closeBtn = document.createElement('span');
        closeBtn.className = 'right-panel-tab-close';
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

    show(key) {
        const view = this._views[key];
        if (!view) return;
        this._openViews.add(key);

        // Deactivate previous (keep 'open', only remove 'active')
        if (this._activeView && this._activeView !== key) {
            const prev = this._views[this._activeView];
            prev.element.style.display = 'none';
            prev._tab.classList.remove('active');
            if (prev.onDeactivate) prev.onDeactivate();
        }

        // Activate new
        view.element.style.display = '';
        view._tab.classList.add('open', 'active');
        this._activeView = key;
        this._titleEl.textContent = '';
        if (view.titleElement) {
            this._titleEl.appendChild(view.titleElement);
        } else {
            this._titleEl.textContent = view.title || '';
        }
        // Custom buttons slot
        this._customBtnSlot.textContent = '';
        if (view.titleButtons) {
            for (const btn of view.titleButtons) this._customBtnSlot.appendChild(btn);
        }
        // Show undock button if view supports it
        this._undockBtn.style.display = view.undockable ? '' : 'none';
        if (view.onActivate) view.onActivate();
    }

    onUndock(callback) {
        this._onUndock = callback;
    }

    close(key) {
        this._openViews.delete(key);
        const view = this._views[key];
        if (view?._tab) view._tab.classList.remove('open', 'active');
        if (this._activeView === key) {
            const remaining = [...this._openViews];
            if (remaining.length > 0) {
                this.show(remaining[remaining.length - 1]);
            } else {
                if (this._onClose) this._onClose();
            }
        }
    }

    toggle(key) {
        if (this._openViews.has(key)) {
            this.close(key);
        } else {
            this.show(key);
        }
    }

    set onClose(cb) { this._onClose = cb; }
    get openViews() { return this._openViews; }

    updateViewTitle(key, title) {
        const view = this._views[key];
        if (!view) return;
        view.title = title;
        if (this._activeView === key) {
            this._titleEl.textContent = title;
        }
    }

    /** Set the status LED: 'connected', 'disconnected', or 'connecting' */
    setStatusLed(state) {
        this._statusLed.className = `right-panel-status-led ${state}`;
        const labels = { connected: 'Connected', disconnected: 'Disconnected', connecting: 'Connecting...' };
        this._statusLabel.textContent = labels[state] || '';
    }

    get activeView() {
        return this._activeView;
    }
}

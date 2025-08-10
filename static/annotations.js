document.addEventListener('DOMContentLoaded', () => {
    const textDiv = document.getElementById('text-display');

    function initOffsets() {
        document.querySelectorAll('.entity-mark').forEach(span => {
            const range = document.createRange();
            range.selectNodeContents(textDiv);
            range.setEndBefore(span);
            const start = range.toString().length;
            const end = start + span.textContent.length;
            span.dataset.start = start;
            span.dataset.end = end;
        });
    }
    initOffsets();

    const availableTypes = Array.from(
        new Set(Array.from(document.querySelectorAll('.entity-mark'))
            .map(s => s.dataset.type)
            .filter(Boolean))
    );

    // Popup for editing entity type and normalized value. Uses a datalist
    // so new types can be entered while still suggesting existing ones.
    const editPopup = document.createElement('div');
    editPopup.className = 'annotation-popup';
    editPopup.style.display = 'none';

    const typeInput = document.createElement('input');
    typeInput.setAttribute('list', 'entity-types');

    const typeList = document.createElement('datalist');
    typeList.id = 'entity-types';
    availableTypes.forEach(t => {
        const opt = document.createElement('option');
        opt.value = t;
        typeList.appendChild(opt);
    });

    const normInput = document.createElement('input');
    normInput.placeholder = 'Normalized (optional)';

    const saveBtn = document.createElement('button');
    saveBtn.textContent = 'Save';

    const cancelBtn = document.createElement('button');
    cancelBtn.textContent = 'Cancel';

    editPopup.appendChild(typeInput);
    editPopup.appendChild(typeList);
    editPopup.appendChild(normInput);
    editPopup.appendChild(saveBtn);
    editPopup.appendChild(cancelBtn);
    document.body.appendChild(editPopup);

    const actionPopup = document.createElement('div');
    actionPopup.className = 'annotation-popup';
    actionPopup.style.display = 'none';
    const actionEditBtn = document.createElement('button');
    actionEditBtn.textContent = 'Edit';
    const actionDeleteBtn = document.createElement('button');
    actionDeleteBtn.textContent = 'Delete';
    actionPopup.appendChild(actionEditBtn);
    actionPopup.appendChild(actionDeleteBtn);
    document.body.appendChild(actionPopup);

    let currentSpan = null;
    let addRange = null;
    let editMode = false;
    let addMode = false;

    function showActionPopup(span) {
        if (!span) return;
        const rect = span.getBoundingClientRect();
        actionPopup.style.display = 'block';
        actionPopup.style.top = `${window.scrollY + rect.bottom + 5}px`;
        actionPopup.style.left = `${window.scrollX + rect.left}px`;
    }

    function showEditPopup(span, rect) {
        if (span) {
            typeInput.value = span.dataset.type || '';
            normInput.value = span.dataset.norm || '';
        } else {
            typeInput.value = '';
            normInput.value = '';
        }
        editPopup.style.display = 'block';
        const r = rect || (span ? span.getBoundingClientRect() : null);
        if (r) {
            const popupH = editPopup.offsetHeight;
            editPopup.style.top = `${window.scrollY + r.top - popupH - 5}px`;
            editPopup.style.left = `${window.scrollX + r.left}px`;
        }
        currentSpan = span;
    }

    function saveEntity(span) {
        if (!span) return;
        const fd = new FormData();
        fd.append('action', 'update');
        fd.append('id', span.dataset.id);
        const s = parseInt(span.dataset.start, 10);
        const e = parseInt(span.dataset.end, 10);
        if (!Number.isNaN(s) && !Number.isNaN(e)) {
            const start = Math.min(s, e);
            const end = Math.max(s, e);
            fd.append('start', start);
            fd.append('end', end);
            span.dataset.start = start;
            span.dataset.end = end;
        } else {
            if (span.dataset.start !== undefined) fd.append('start', span.dataset.start);
            if (span.dataset.end !== undefined) fd.append('end', span.dataset.end);
        }
        if (span.dataset.type) fd.append('type', span.dataset.type);
        if (span.dataset.norm) fd.append('norm', span.dataset.norm);
        fetch(window.location.pathname + window.location.search, { method: 'POST', body: fd });
    }

    actionEditBtn.addEventListener('click', ev => {
        ev.stopPropagation();
        if (!currentSpan) return;
        actionPopup.style.display = 'none';
        const row = document.querySelector(`#entity-table tr[data-id="${currentSpan.dataset.id}"]`);
        const btn = row ? row.querySelector('.edit-entity') : null;
        if (btn) btn.click();
    });

    actionDeleteBtn.addEventListener('click', ev => {
        ev.stopPropagation();
        if (!currentSpan) return;
        const fd = new FormData();
        fd.append('action', 'delete');
        fd.append('id', currentSpan.dataset.id);
        fetch(window.location.pathname + window.location.search, { method: 'POST', body: fd })
            .then(() => window.location.reload());
    });

    saveBtn.addEventListener('click', () => {
        const newType = typeInput.value.trim();
        const newNorm = normInput.value.trim();
        if (currentSpan) {
            currentSpan.dataset.type = newType;
            if (newNorm) {
                currentSpan.dataset.norm = newNorm;
            } else {
                delete currentSpan.dataset.norm;
            }
            const row = document.querySelector(`#entity-table tr[data-id="${currentSpan.dataset.id}"]`);
            if (row) {
                row.dataset.type = newType;
                row.dataset.norm = newNorm;
                const cell = row.querySelector('td:nth-child(2)');
                if (cell) cell.textContent = newType;
            }
            saveEntity(currentSpan);
        } else if (addRange) {
            const fd = new FormData();
            fd.append('action', 'add');
            fd.append('start', addRange.start);
            fd.append('end', addRange.end);
            fd.append('type', newType);
            if (newNorm) fd.append('norm', newNorm);
            fetch(window.location.pathname + window.location.search, { method: 'POST', body: fd })
                .then(() => window.location.reload());
            addRange = null;
            addMode = false;
        }
        // update suggestions if new type introduced
        if (newType && !availableTypes.includes(newType)) {
            availableTypes.push(newType);
            const opt = document.createElement('option');
            opt.value = newType;
            typeList.appendChild(opt);
        }
        editPopup.style.display = 'none';
    });

    cancelBtn.addEventListener('click', () => {
        editPopup.style.display = 'none';
        if (addMode) {
            addMode = false;
            addRange = null;
        }
    });

    document.addEventListener('click', ev => {
        if (!editPopup.contains(ev.target)) {
            editPopup.style.display = 'none';
            if (!ev.target.closest('.entity-mark') && !ev.target.closest('.entity-handle')) {
                editMode = false;
            }
            if (addMode) {
                addMode = false;
                addRange = null;
            }
        }
        if (!actionPopup.contains(ev.target) && !ev.target.closest('.entity-mark')) {
            actionPopup.style.display = 'none';
        }
        if (!ev.target.closest('.entity-mark') && !ev.target.closest('.entity-handle')) {
            document.querySelectorAll('.entity-mark').forEach(s => s.classList.remove('selected'));
            hideHandles();
            currentSpan = null;
        }
    });

    const startHandle = document.createElement('div');
    startHandle.className = 'entity-handle';
    startHandle.textContent = '[';
    startHandle.style.display = 'none';
    document.body.appendChild(startHandle);

    const endHandle = document.createElement('div');
    endHandle.className = 'entity-handle';
    endHandle.textContent = ']';
    endHandle.style.display = 'none';
    document.body.appendChild(endHandle);

    function hideHandles() {
        startHandle.style.display = 'none';
        endHandle.style.display = 'none';
    }

    function getRectAtOffset(offset) {
        const walker = document.createTreeWalker(textDiv, NodeFilter.SHOW_TEXT);
        let count = 0;
        while (walker.nextNode()) {
            const node = walker.currentNode;
            const len = node.textContent.length;
            if (offset <= count + len) {
                const range = document.createRange();
                const pos = offset - count;
                range.setStart(node, pos);
                range.setEnd(node, pos);
                return range.getBoundingClientRect();
            }
            count += len;
        }
        return null;
    }

    function positionHandles(span) {
        if (!editMode || !span) {
            hideHandles();
            return;
        }
        let start = parseInt(span.dataset.start, 10);
        let end = parseInt(span.dataset.end, 10);
        if (Number.isNaN(start) || Number.isNaN(end)) {
            hideHandles();
            return;
        }
        if (start > end) {
            [start, end] = [end, start];
            span.dataset.start = start;
            span.dataset.end = end;
        }
        let startRect = getRectAtOffset(start);
        let endRect = getRectAtOffset(end);
        if (
            !startRect ||
            !endRect ||
            startRect.width === 0 ||
            endRect.width === 0
        ) {
            const rect = span.getBoundingClientRect();
            startRect = { left: rect.left, top: rect.top, height: rect.height };
            endRect = { right: rect.right, top: rect.top, height: rect.height };
        }
        const handleH = startHandle.offsetHeight || 20;
        const startTop = window.scrollY + startRect.top + (startRect.height - handleH) / 2;
        const endTop = window.scrollY + endRect.top + (endRect.height - handleH) / 2;
        startHandle.style.top = `${startTop}px`;
        endHandle.style.top = `${endTop}px`;
        startHandle.style.left = `${window.scrollX + startRect.left}px`;
        endHandle.style.left = `${window.scrollX + endRect.right - endHandle.offsetWidth}px`;
        startHandle.style.display = 'block';
        endHandle.style.display = 'block';
    }

    let dragTarget = null;
    let wasDragging = false;

    function getOffset(node, offset) {
        const range = document.createRange();
        range.selectNodeContents(textDiv);
        range.setEnd(node, offset);
        return range.toString().length;
    }

    function getOffsetFromCoords(x, y) {
        const prevVisStart = startHandle.style.visibility;
        const prevVisEnd = endHandle.style.visibility;
        startHandle.style.visibility = 'hidden';
        endHandle.style.visibility = 'hidden';
        let range;
        if (document.caretPositionFromPoint) {
            const pos = document.caretPositionFromPoint(x, y);
            if (pos) {
                range = document.createRange();
                range.setStart(pos.offsetNode, pos.offset);
            }
        } else if (document.caretRangeFromPoint) {
            range = document.caretRangeFromPoint(x, y);
        }
        startHandle.style.visibility = prevVisStart;
        endHandle.style.visibility = prevVisEnd;
        if (!range) return null;
        const node = range.startContainer;
        const off = range.startOffset;
        if (!textDiv.contains(node)) return null;
        return getOffset(node, off);
    }

    [startHandle, endHandle].forEach(handle => {
        const startDrag = ev => {
            dragTarget = handle === startHandle ? 'start' : 'end';
            wasDragging = false;
            const sel = window.getSelection();
            if (sel) sel.removeAllRanges();
            textDiv.style.userSelect = 'none';
            if (handle.setPointerCapture && ev.pointerId !== undefined) {
                handle.setPointerCapture(ev.pointerId);
            }
            ev.preventDefault();
            ev.stopPropagation();
        };
        handle.addEventListener('mousedown', startDrag);
        handle.addEventListener('pointerdown', startDrag);
        // Some browsers do not bubble move/up events when pointer capture is used,
        // so also listen on the handles themselves to ensure dragging works.
        handle.addEventListener('mousemove', moveHandler);
        handle.addEventListener('pointermove', moveHandler);
        handle.addEventListener('mouseup', endDrag);
        handle.addEventListener('pointerup', endDrag);
    });

    const moveHandler = ev => {
        if (!dragTarget) return;
        const selected = document.querySelector('.entity-mark.selected');
        if (!selected) return;
        ev.preventDefault();
        const offset = getOffsetFromCoords(ev.clientX, ev.clientY);
        if (offset == null) return;
        let start = parseInt(selected.dataset.start || '0', 10);
        let end = parseInt(selected.dataset.end || '0', 10);
        if (dragTarget === 'start') {
            start = Math.min(offset, end);
            selected.dataset.start = start;
        } else {
            end = Math.max(offset, start);
            selected.dataset.end = end;
        }
        setSelectionRange(start, end);
        positionHandles(selected);
        wasDragging = true;
    };
    document.addEventListener('mousemove', moveHandler);
    document.addEventListener('pointermove', moveHandler);

    const endDrag = () => {
        if (!dragTarget) return;
        dragTarget = null;
        textDiv.style.userSelect = '';
        if (wasDragging) {
            saveEntity(document.querySelector('.entity-mark.selected'));
            wasDragging = false;
        }
    };
    document.addEventListener('mouseup', endDrag);
    document.addEventListener('pointerup', endDrag);

    document.addEventListener('click', ev => {
        if (!ev.target.closest('.entity-mark') && !ev.target.closest('.entity-handle')) {
            document.querySelectorAll('.entity-mark').forEach(s => s.classList.remove('selected'));
            hideHandles();
        }
    });

    function setSelectionRange(start, end) {
        if (start > end) [start, end] = [end, start];
        const walker = document.createTreeWalker(textDiv, NodeFilter.SHOW_TEXT);
        let count = 0;
        let sNode = null, sOffset = 0, eNode = null, eOffset = 0;
        while (walker.nextNode()) {
            const node = walker.currentNode;
            const len = node.textContent.length;
            if (!sNode && start <= count + len) {
                sNode = node;
                sOffset = start - count;
            }
            if (!eNode && end <= count + len) {
                eNode = node;
                eOffset = end - count;
                break;
            }
            count += len;
        }
        if (sNode && eNode) {
            const sel = window.getSelection();
            const range = document.createRange();
            range.setStart(sNode, sOffset);
            range.setEnd(eNode, eOffset);
            sel.removeAllRanges();
            sel.addRange(range);
        }
    }

    const addBtn = document.getElementById('add-entity-btn');
    if (addBtn) {
        addBtn.addEventListener('click', ev => {
            ev.stopPropagation();
            addMode = true;
            const sel = window.getSelection();
            if (sel) sel.removeAllRanges();
            document.querySelectorAll('.entity-mark').forEach(s => s.classList.remove('selected'));
            hideHandles();
            currentSpan = null;
        });
    }

    textDiv.addEventListener('mouseup', ev => {
        if (!addMode) return;
        const sel = window.getSelection();
        if (!sel || sel.isCollapsed) return;
        const range = sel.getRangeAt(0);
        if (!textDiv.contains(range.startContainer) || !textDiv.contains(range.endContainer)) return;
        let start = getOffset(range.startContainer, range.startOffset);
        let end = getOffset(range.endContainer, range.endOffset);
        if (start > end) [start, end] = [end, start];
        addRange = { start, end };
        showEditPopup(null, range.getBoundingClientRect());
    });

    document.querySelectorAll('.edit-entity').forEach(btn => {
        btn.addEventListener('click', ev => {
            ev.stopPropagation();
            const tr = btn.closest('tr');
            if (!tr) return;
            document.querySelectorAll('.entity-mark').forEach(s => s.classList.remove('selected'));
            const span = document.querySelector(`.entity-mark[data-id="${tr.dataset.id}"]`);
            if (span) {
                editMode = true;
                span.classList.add('selected');
                currentSpan = span;
                const start = parseInt(span.dataset.start, 10);
                const end = parseInt(span.dataset.end, 10);
                if (!Number.isNaN(start) && !Number.isNaN(end)) {
                    setSelectionRange(start, end);
                    positionHandles(span);
                } else {
                    hideHandles();
                }
                actionPopup.style.display = 'none';
                showEditPopup(span);
            }
        });
    });

    document.querySelectorAll('.entity-mark').forEach(span => {
        span.addEventListener('click', () => {
            document.querySelectorAll('.entity-mark').forEach(s => s.classList.remove('selected'));
            span.classList.add('selected');
            currentSpan = span;
            editMode = false;
            // Remove any existing text selection to prevent the browser from
            // highlighting text when entities are clicked.
            const sel = window.getSelection();
            if (sel) sel.removeAllRanges();
            hideHandles();
            showActionPopup(span);
        });
    });
});


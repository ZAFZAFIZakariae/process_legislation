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

    const typePopup = document.createElement('div');
    typePopup.className = 'annotation-popup';
    typePopup.style.display = 'none';
    const typeSelect = document.createElement('select');
    availableTypes.forEach(t => {
        const opt = document.createElement('option');
        opt.value = t;
        opt.textContent = t;
        typeSelect.appendChild(opt);
    });
    typePopup.appendChild(typeSelect);
    document.body.appendChild(typePopup);

    let currentSpan = null;
    let addRange = null;
    let editMode = false;
    let addMode = false;

    function showTypePopup(span, rect) {
        if (span) {
            typeSelect.value = span.dataset.type || '';
        }
        typePopup.style.display = 'block';
        const r = rect || (span ? span.getBoundingClientRect() : null);
        if (r) {
            const popupH = typePopup.offsetHeight;
            typePopup.style.top = `${window.scrollY + r.top - popupH - 5}px`;
            typePopup.style.left = `${window.scrollX + r.left}px`;
        }
        currentSpan = span;
    }

    function saveEntity(span) {
        if (!span) return;
        const fd = new FormData();
        fd.append('action', 'update');
        fd.append('id', span.dataset.id);
        if (span.dataset.start !== undefined) fd.append('start', span.dataset.start);
        if (span.dataset.end !== undefined) fd.append('end', span.dataset.end);
        if (span.dataset.type) fd.append('type', span.dataset.type);
        if (span.dataset.norm) fd.append('norm', span.dataset.norm);
        fetch(window.location.pathname + window.location.search, { method: 'POST', body: fd });
    }

    typeSelect.addEventListener('change', () => {
        const newType = typeSelect.value;
        if (currentSpan) {
            currentSpan.dataset.type = newType;
            const row = document.querySelector(`#entity-table tr[data-id="${currentSpan.dataset.id}"]`);
            if (row) {
                row.dataset.type = newType;
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
            fetch(window.location.pathname + window.location.search, { method: 'POST', body: fd })
                .then(() => window.location.reload());
            addRange = null;
            addMode = false;
        }
        typePopup.style.display = 'none';
    });

    document.addEventListener('click', ev => {
        if (!typePopup.contains(ev.target)) {
            typePopup.style.display = 'none';
            if (!ev.target.closest('.entity-mark') && !ev.target.closest('.entity-handle')) {
                editMode = false;
            }
        }
        if (!ev.target.closest('.entity-mark') && !ev.target.closest('.entity-handle')) {
            document.querySelectorAll('.entity-mark').forEach(s => s.classList.remove('selected'));
            hideHandles();
            currentSpan = null;
            if (addMode) {
                addMode = false;
                addRange = null;
            }
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
        if (!span) {
            hideHandles();
            return;
        }
        const start = parseInt(span.dataset.start, 10);
        const end = parseInt(span.dataset.end, 10);
        if (Number.isNaN(start) || Number.isNaN(end)) {
            hideHandles();
            return;
        }
        const startRect = getRectAtOffset(start);
        const endRect = getRectAtOffset(end);
        if (!startRect || !endRect) {
            hideHandles();
            return;
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
        addBtn.addEventListener('click', () => {
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
        const start = getOffset(range.startContainer, range.startOffset);
        const end = getOffset(range.endContainer, range.endOffset);
        addRange = { start, end };
        showTypePopup(null, range.getBoundingClientRect());
    });

    document.querySelectorAll('.edit-entity').forEach(btn => {
        btn.addEventListener('click', () => {
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
                showTypePopup(span);
            }
        });
    });
});


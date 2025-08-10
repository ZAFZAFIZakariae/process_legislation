document.addEventListener('DOMContentLoaded', () => {
    const textDiv = document.getElementById('text-display');
    const addStart = document.getElementById('add-start');
    const addEnd = document.getElementById('add-end');
    const updId = document.getElementById('upd-id');
    const updType = document.getElementById('upd-type');
    const updNorm = document.getElementById('upd-norm');
    const updStart = document.getElementById('upd-start');
    const updEnd = document.getElementById('upd-end');
    const nudgeStartBtns = document.querySelectorAll('.nudge-start');
    const nudgeEndBtns = document.querySelectorAll('.nudge-end');
    const repStart = document.getElementById('rep-start');
    const repEnd = document.getElementById('rep-end');
    const updateForm = document.getElementById('update-form');

    // Build list of available entity types from existing spans
    const availableTypes = Array.from(
        new Set(Array.from(document.querySelectorAll('.entity-mark'))
            .map(s => s.dataset.type)
            .filter(Boolean))
    );

    // Popup for changing entity types
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

    function showTypePopup(span) {
        if (!span) return;
        typeSelect.value = span.dataset.type || '';
        typePopup.style.display = 'block';
        // Ensure the popup does not obscure the entity by positioning
        // it *above* after we know its rendered height.
        const rect = span.getBoundingClientRect();
        const popupH = typePopup.offsetHeight;
        typePopup.style.top = `${window.scrollY + rect.top - popupH - 5}px`;
        typePopup.style.left = `${window.scrollX + rect.left}px`;
        currentSpan = span;
    }

    typeSelect.addEventListener('change', () => {
        if (!currentSpan) return;
        const newType = typeSelect.value;
        updId.value = currentSpan.dataset.id;
        updType.value = newType;
        updateForm.submit();
        typePopup.style.display = 'none';
    });

    document.addEventListener('click', ev => {
        if (!typePopup.contains(ev.target)) {
            typePopup.style.display = 'none';
        }
    });

    // Floating handles for adjusting entity offsets in the text view
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

    function positionHandles(span) {
        if (!span) {
            hideHandles();
            return;
        }
        // Always base the handle positions on the span's bounding box so
        // the brackets initially wrap the entity that was clicked.
        const rect = span.getBoundingClientRect();
        const handleH = startHandle.offsetHeight || 20;
        const top = window.scrollY + rect.top + (rect.height - handleH) / 2;
        startHandle.style.top = `${top}px`;
        startHandle.style.left = `${window.scrollX + rect.left}px`;
        endHandle.style.top = `${top}px`;
        endHandle.style.left = `${window.scrollX + rect.right - endHandle.offsetWidth}px`;
        startHandle.style.display = 'block';
        endHandle.style.display = 'block';
    }

    let dragTarget = null;
    let wasDragging = false;
    let pendingHandle = null;

    function getOffsetFromCoords(x, y) {
        // Temporarily hide the handles so caret lookup uses the underlying text
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
        const offset = range.startOffset;
        if (!textDiv.contains(node)) return null;
        return getOffset(node, offset);
    }

    [startHandle, endHandle].forEach(handle => {
        const startDrag = ev => {
            dragTarget = handle === startHandle ? 'start' : 'end';
            pendingHandle = null;
            wasDragging = false;
            if (handle.setPointerCapture && ev.pointerId !== undefined) {
                handle.setPointerCapture(ev.pointerId);
            }
            ev.preventDefault();
            ev.stopPropagation();
        };
        handle.addEventListener('mousedown', startDrag);
        handle.addEventListener('pointerdown', startDrag);
        handle.addEventListener('click', ev => {
            if (wasDragging) { wasDragging = false; return; }
            pendingHandle = handle === startHandle ? 'start' : 'end';
            ev.stopPropagation();
        });
    });
    const moveHandler = ev => {
        if (!dragTarget) return;
        const selected = document.querySelector('.entity-mark.selected');
        if (!selected) return;
        const offset = getOffsetFromCoords(ev.clientX, ev.clientY);
        if (offset == null) return;
        let start = parseInt(updStart.value || '0', 10);
        let end = parseInt(updEnd.value || '0', 10);
        if (dragTarget === 'start') {
            start = Math.min(offset, end);
            updStart.value = start;
            selected.dataset.start = start;
        } else {
            end = Math.max(offset, start);
            updEnd.value = end;
            selected.dataset.end = end;
        }
        setSelectionRange(start, end);
        positionHandles(selected);
        wasDragging = true;
    };

    document.addEventListener('mousemove', moveHandler);
    document.addEventListener('pointermove', moveHandler);

    const endDrag = () => { dragTarget = null; };
    document.addEventListener('mouseup', endDrag);
    document.addEventListener('pointerup', endDrag);

    document.addEventListener('click', ev => {
        if (!ev.target.closest('.entity-mark')) {
            document.querySelectorAll('.entity-mark').forEach(s => s.classList.remove('selected'));
            hideHandles();
        }
    });

    function getOffset(node, offset) {
        const range = document.createRange();
        range.selectNodeContents(textDiv);
        range.setEnd(node, offset);
        return range.toString().length;
    }

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

    textDiv.addEventListener('mouseup', () => {
        const sel = window.getSelection();
        if (!sel || sel.rangeCount === 0) return;
        const range = sel.getRangeAt(0);
        if (!textDiv.contains(range.startContainer) || !textDiv.contains(range.endContainer)) return;
        const start = getOffset(range.startContainer, range.startOffset);
        const end = getOffset(range.endContainer, range.endOffset);
        const selected = document.querySelector('.entity-mark.selected');

        if (pendingHandle && selected) {
            let s = parseInt(updStart.value || selected.dataset.start || '0', 10);
            let e = parseInt(updEnd.value || selected.dataset.end || '0', 10);
            if (pendingHandle === 'start') {
                s = Math.min(start, e);
                updStart.value = s;
                selected.dataset.start = s;
            } else {
                e = Math.max(end, s);
                updEnd.value = e;
                selected.dataset.end = e;
            }
            setSelectionRange(s, e);
            positionHandles(selected);
            pendingHandle = null;
            return;
        }

        addStart.value = start;
        addEnd.value = end;
        repStart.value = start;
        repEnd.value = end;
        if (selected) {
            const curStart = parseInt(updStart.value || selected.dataset.start || '0', 10);
            const curEnd = parseInt(updEnd.value || selected.dataset.end || '0', 10);
            if (start === end) {
                const distToStart = Math.abs(start - curStart);
                const distToEnd = Math.abs(end - curEnd);
                if (distToStart <= distToEnd) {
                    updStart.value = start;
                    selected.dataset.start = updStart.value;
                    setSelectionRange(start, curEnd);
                } else {
                    updEnd.value = end;
                    selected.dataset.end = updEnd.value;
                    setSelectionRange(curStart, end);
                }
            } else {
                updStart.value = start;
                updEnd.value = end;
                selected.dataset.start = updStart.value;
                selected.dataset.end = updEnd.value;
                setSelectionRange(start, end);
            }
            positionHandles(selected);
        }
    });

    document.querySelectorAll('.entity-mark').forEach(span => {
        span.addEventListener('click', ev => {
            ev.stopPropagation();
            document.querySelectorAll('.entity-mark').forEach(s => s.classList.remove('selected'));
            span.classList.add('selected');
            updId.value = span.dataset.id;
            updType.value = span.dataset.type || '';
            updNorm.value = span.dataset.norm || '';
            updStart.value = span.dataset.start;
            updEnd.value = span.dataset.end;
            setSelectionRange(parseInt(span.dataset.start), parseInt(span.dataset.end));
            positionHandles(span);
            showTypePopup(span);
        });
    });

    document.querySelectorAll('.edit-entity').forEach(btn => {
        btn.addEventListener('click', () => {
            const tr = btn.closest('tr');
            if (!tr) return;
            document.querySelectorAll('.entity-mark').forEach(s => s.classList.remove('selected'));
            const span = document.querySelector(`.entity-mark[data-id="${tr.dataset.id}"]`);
            if (span) span.classList.add('selected');
            updId.value = tr.dataset.id;
            updType.value = tr.dataset.type || '';
            updNorm.value = tr.dataset.norm || '';
            updStart.value = tr.dataset.start;
            updEnd.value = tr.dataset.end;
            setSelectionRange(parseInt(tr.dataset.start), parseInt(tr.dataset.end));
            positionHandles(span);
        });
    });

    nudgeStartBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const delta = parseInt(btn.dataset.delta, 10) || 0;
            let start = parseInt(updStart.value || '0', 10) + delta;
            let end = parseInt(updEnd.value || '0', 10);
            if (start < 0) start = 0;
            if (start > end) start = end;
            updStart.value = start;
            setSelectionRange(start, end);
            positionHandles(document.querySelector('.entity-mark.selected'));
        });
    });

    nudgeEndBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const delta = parseInt(btn.dataset.delta, 10) || 0;
            let start = parseInt(updStart.value || '0', 10);
            let end = parseInt(updEnd.value || '0', 10) + delta;
            if (end < start) end = start;
            updEnd.value = end;
            setSelectionRange(start, end);
            positionHandles(document.querySelector('.entity-mark.selected'));
        });
    });
});

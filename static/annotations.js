document.addEventListener('DOMContentLoaded', () => {
    const textDiv = document.getElementById('text-display');
    const addStart = document.getElementById('add-start');
    const addEnd = document.getElementById('add-end');
    const updId = document.getElementById('upd-id');
    const updType = document.getElementById('upd-type');
    const updNorm = document.getElementById('upd-norm');
    const updStart = document.getElementById('upd-start');
    const updEnd = document.getElementById('upd-end');
    const repStart = document.getElementById('rep-start');
    const repEnd = document.getElementById('rep-end');

    function getOffset(node, offset) {
        const range = document.createRange();
        range.selectNodeContents(textDiv);
        range.setEnd(node, offset);
        return range.toString().length;
    }

    textDiv.addEventListener('mouseup', () => {
        const sel = window.getSelection();
        if (!sel || sel.rangeCount === 0) return;
        const range = sel.getRangeAt(0);
        if (!textDiv.contains(range.startContainer) || !textDiv.contains(range.endContainer)) return;
        const start = getOffset(range.startContainer, range.startOffset);
        const end = getOffset(range.endContainer, range.endOffset);
        addStart.value = start;
        addEnd.value = end;
        repStart.value = start;
        repEnd.value = end;
    });

    document.querySelectorAll('.entity-mark').forEach(span => {
        span.addEventListener('click', () => {
            document.querySelectorAll('.entity-mark').forEach(s => s.classList.remove('selected'));
            span.classList.add('selected');
            updId.value = span.dataset.id;
            updType.value = span.dataset.type || '';
            updNorm.value = span.dataset.norm || '';
            updStart.value = span.dataset.start;
            updEnd.value = span.dataset.end;
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
        });
    });
});

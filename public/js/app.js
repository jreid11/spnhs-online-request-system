(() => {
  const navToggle = document.querySelector('[data-nav-toggle]');
  const nav = document.querySelector('[data-nav]');
  if (navToggle && nav) navToggle.addEventListener('click', () => nav.classList.toggle('open'));

  const requestTypeInputs = [...document.querySelectorAll('input[name="request_type"]')];
  const leaveType = document.querySelector('[data-leave-type]');

  function updateRequestType() {
    const selected = requestTypeInputs.find(input => input.checked);
    document.body.dataset.requestType = selected ? selected.value : '';

    document.querySelectorAll('.simple-only input').forEach(input => {
      input.required = selected && (selected.value === 'COE' || selected.value === 'SERVICE_RECORD');
    });
    document.querySelectorAll('.form6-only input, .form6-only select').forEach(input => {
      const requiredNames = ['middle_name','date_filing','position','salary','leave_type','working_days','inclusive_dates','commutation'];
      input.required = selected && selected.value === 'FORM_6' && requiredNames.includes(input.name);
    });
  }

  function updateLeaveType() {
    document.body.dataset.leaveType = leaveType ? leaveType.value : '';
    const other = document.querySelector('input[name="other_leave_type"]');
    if (other) other.required = leaveType && leaveType.value === 'Others';
  }

  requestTypeInputs.forEach(input => input.addEventListener('change', updateRequestType));
  if (leaveType) leaveType.addEventListener('change', updateLeaveType);
  updateRequestType();
  updateLeaveType();

  document.querySelectorAll('[data-copy]').forEach(button => {
    button.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(button.dataset.copy || '');
        const original = button.textContent;
        button.textContent = 'Copied';
        setTimeout(() => button.textContent = original, 1600);
      } catch (_) {
        window.prompt('Copy this tracking number:', button.dataset.copy || '');
      }
    });
  });
})();

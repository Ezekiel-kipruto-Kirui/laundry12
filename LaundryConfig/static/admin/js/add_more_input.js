// laundry/static/admin/js/add_more_input.js
document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".add-more-btn").forEach(function (btn) {
        btn.addEventListener("click", function () {
            const container = btn.closest(".add-more-container");
            
            // Find the last input in the container
            const lastInput = container.querySelector("input:last-of-type");
            
            // Clone the input field
            const newInput = lastInput.cloneNode(true);
            newInput.value = "";
            
            // Insert before button
            container.insertBefore(newInput, btn);
            
            // Add a small margin between items
            if (container.querySelectorAll("input").length > 1) {
                newInput.classList.add("mt-2");
            }
        });
    });
});
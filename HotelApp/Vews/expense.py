from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.db import DatabaseError
from django.db.models import Sum
from django.http import JsonResponse, Http404
from django.views.generic import ListView, CreateView, UpdateView, DeleteView
from django.urls import reverse_lazy
from django.core.exceptions import PermissionDenied, ValidationError
from ..models import Business, ExpenseField, ExpenseRecord
from ..forms import ExpenseFieldForm, ExpenseRecordForm

class BusinessListView(ListView):
    model = Business
    template_name = 'expenses/business_list.html'
    context_object_name = 'businesses'

    def get_queryset(self):
        try:
            # Ensure Hotel and Laundry shops exist
            default_businesses = ['Hotel', 'Laundry Shop']
            for business_name in default_businesses:
                Business.objects.get_or_create(name=business_name)
            return Business.objects.all()
        except DatabaseError as e:
            messages.error(self.request, f'Database error: {str(e)}')
            return Business.objects.none()
        except Exception as e:
            messages.error(self.request, f'Unexpected error: {str(e)}')
            return Business.objects.none()

class ExpenseDashboardView(ListView):
    model = ExpenseRecord
    template_name = 'expenses/expense_dashboard.html'
    context_object_name = 'expense_records'

    def get_queryset(self):
        try:
            self.business = get_object_or_404(Business, pk=self.kwargs['business_id'])
            return ExpenseRecord.objects.filter(
                business=self.business
            ).select_related('expense_field').order_by('-expense_date')
        except DatabaseError as e:
            messages.error(self.request, f'Database error while loading expenses: {str(e)}')
            return ExpenseRecord.objects.none()
        except Exception as e:
            messages.error(self.request, f'Unexpected error: {str(e)}')
            return ExpenseRecord.objects.none()

    def get_context_data(self, **kwargs):
        try:
            context = super().get_context_data(**kwargs)
            business = self.business
            
            # Total expenses for the business
            total_expenses = self.get_queryset().aggregate(total=Sum('amount'))['total'] or 0
            
            # Expenses by category
            expenses_by_category = ExpenseRecord.objects.filter(business=business).values(
                'expense_field__label'
            ).annotate(
                total=Sum('amount')
            ).order_by('-total')
            
            # Expense fields for this business
            expense_fields = ExpenseField.objects.filter(business=business)
            
            context.update({
                'business': business,
                'total_expenses': total_expenses,
                'expenses_by_category': expenses_by_category,
                'expense_fields': expense_fields,
                'expense_form': ExpenseRecordForm(business_id=business.id),
                'field_form': ExpenseFieldForm(initial={'business': business})
            })
            return context
        except DatabaseError as e:
            messages.error(self.request, f'Database error while loading dashboard: {str(e)}')
            # Return basic context even if there are database errors
            return {
                'business': get_object_or_404(Business, pk=self.kwargs['business_id']),
                'total_expenses': 0,
                'expenses_by_category': [],
                'expense_fields': [],
                'expense_form': ExpenseRecordForm(),
                'field_form': ExpenseFieldForm()
            }
        except Exception as e:
            messages.error(self.request, f'Unexpected error: {str(e)}')
            raise Http404("Page not available due to technical issues")

class ExpenseFieldCreateView(CreateView):
    model = ExpenseField
    form_class = ExpenseFieldForm
    template_name = 'expenses/expense_field_form.html'

    def form_valid(self, form):
        try:
            response = super().form_valid(form)
            messages.success(self.request, 'Expense category created successfully!')
            return response
        except DatabaseError as e:
            messages.error(self.request, f'Database error: {str(e)}')
            return self.form_invalid(form)
        except Exception as e:
            messages.error(self.request, f'Unexpected error: {str(e)}')
            return self.form_invalid(form)

    def form_invalid(self, form):
        messages.error(self.request, 'Please correct the errors below.')
        return super().form_invalid(form)

    def get_success_url(self):
        return reverse_lazy('expense_dashboard', kwargs={'business_id': self.object.business.id})

class ExpenseRecordCreateView(CreateView):
    model = ExpenseRecord
    form_class = ExpenseRecordForm
    template_name = 'expenses/expense_record_form.html'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['business_id'] = self.kwargs['business_id']
        return kwargs

    def form_valid(self, form):
        try:
            # Set the business before saving
            form.instance.business_id = self.kwargs['business_id']
            response = super().form_valid(form)
            messages.success(self.request, 'Expense record added successfully!')
            return response
        except DatabaseError as e:
            messages.error(self.request, f'Database error: {str(e)}')
            return self.form_invalid(form)
        except Exception as e:
            messages.error(self.request, f'Unexpected error: {str(e)}')
            return self.form_invalid(form)

    def form_invalid(self, form):
        messages.error(self.request, 'Please correct the errors below.')
        return super().form_invalid(form)

    def get_success_url(self):
        return reverse_lazy('expense_dashboard', kwargs={'business_id': self.kwargs['business_id']})

class ExpenseRecordUpdateView(UpdateView):
    model = ExpenseRecord
    form_class = ExpenseRecordForm
    template_name = 'expenses/expense_record_form.html'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['business_id'] = self.object.business.id
        return kwargs

    def form_valid(self, form):
        try:
            response = super().form_valid(form)
            messages.success(self.request, 'Expense record updated successfully!')
            return response
        except DatabaseError as e:
            messages.error(self.request, f'Database error: {str(e)}')
            return self.form_invalid(form)
        except Exception as e:
            messages.error(self.request, f'Unexpected error: {str(e)}')
            return self.form_invalid(form)

    def form_invalid(self, form):
        messages.error(self.request, 'Please correct the errors below.')
        return super().form_invalid(form)

    def get_success_url(self):
        return reverse_lazy('expense_dashboard', kwargs={'business_id': self.object.business.id})

class ExpenseRecordDeleteView(DeleteView):
    model = ExpenseRecord
    template_name = 'expenses/expense_record_confirm_delete.html'

    def delete(self, request, *args, **kwargs):
        try:
            messages.success(self.request, 'Expense record deleted successfully!')
            return super().delete(request, *args, **kwargs)
        except DatabaseError as e:
            messages.error(self.request, f'Database error: {str(e)}')
            return redirect('expense_dashboard', business_id=self.get_object().business.id)
        except Exception as e:
            messages.error(self.request, f'Unexpected error: {str(e)}')
            return redirect('expense_dashboard', business_id=self.get_object().business.id)

    def get_success_url(self):
        return reverse_lazy('expense_dashboard', kwargs={'business_id': self.object.business.id})

def delete_expense_field(request, pk):
    try:
        expense_field = get_object_or_404(ExpenseField, pk=pk)
        business_id = expense_field.business.id
        
        # Check if there are any expense records using this field
        if expense_field.expense_records.exists():
            messages.error(request, 'Cannot delete category that has expense records. Please delete the records first.')
            return redirect('expense_dashboard', business_id=business_id)
            
        expense_field.delete()
        messages.success(request, 'Expense category deleted successfully!')
    except DatabaseError as e:
        messages.error(request, f'Database error: {str(e)}')
    except Exception as e:
        messages.error(request, f'Unexpected error: {str(e)}')
    
    return redirect('expense_dashboard', business_id=business_id)
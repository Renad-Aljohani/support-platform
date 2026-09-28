from pytz import UTC
from dateutil.relativedelta import relativedelta

from odoo import models, fields, api
from odoo.exceptions import ValidationError

class SupportTicket(models.Model):
    _name = 'support.ticket'
    _inherit = ['mail.thread']
    _description = 'Support Ticket'
    _order = 'create_date desc'

    ticket_number = fields.Char(
        string='رقم الطلب',
        copy=False,
        readonly=True,
    )

    title = fields.Char(
        string='موضوع الطلب',
    )

    description = fields.Text(
        string='وصف المشكلة',
    )

    category_id = fields.Many2one(
        'support.category',
        string='التصنيف',
        ondelete='restrict',
    )

    priority = fields.Selection(
        [
            ('low', 'منخفضة'),
            ('medium', 'متوسطة'),
            ('high', 'عالية'),
        ],
        string='الأولوية',
    )

    status = fields.Selection(
        [
            ('draft', 'مسودة'),
            ('new', 'جديد'),
            ('processing', 'قيد المعالجة'),
            ('on_hold', 'معلق مؤقتًا'),
            ('waiting_confirmation', 'بانتظار تأكيد الموظف'),
            ('closed', 'مغلق'),
        ],
        string='الحالة',
        required=True,
        default='draft',
        tracking=True,
    )

    requester_id = fields.Many2one(
        'res.users',
        string='صاحب الطلب',
        required=True,
        default=lambda self: self.env.user,
    )

    assignee_id = fields.Many2one(
        'res.users',
        string='مسؤول الدعم',
        tracking=True,
    )

    department_id = fields.Many2one(
        'hr.department',
        string='الإدارة',
    )

    solution = fields.Text(
        string='الحل',
    )

    solution_at = fields.Datetime(
        string='تاريخ تسجيل الحل',
    )

    closed_at = fields.Datetime(
        string='تاريخ الإغلاق',
    )

    reopen_count = fields.Integer(
        string='عدد مرات إعادة الفتح',
        default=0,
        readonly=True,
    )

    sla_pause_started_at = fields.Datetime(
        string='بداية إيقاف SLA',
        readonly=True,
    )

    sla_pause_reason = fields.Selection(
        [
            ('waiting_employee', 'بانتظار الموظف'),
            ('waiting_approval', 'بانتظار موافقة'),
            ('waiting_internal', 'بانتظار جهة داخلية'),
            ('scheduled', 'بانتظار موعد مجدول'),
        ],
        string='سبب إيقاف SLA',
        readonly=True,
    )

    sla_paused_hours = fields.Float(
        string='إجمالي ساعات إيقاف SLA',
        default=0.0,
        readonly=True,
    )

    sla_pause_count = fields.Integer(
        string='عدد مرات إيقاف SLA',
        default=0,
        readonly=True,
    )  

     
    submitted_at = fields.Datetime(
    string='تاريخ إرسال الطلب',
    readonly=True,
    copy=False,
    )
    
    sla_response_deadline = fields.Datetime(
        string='الموعد النهائي للاستجابة',
        readonly=True,
    )

    sla_resolution_deadline = fields.Datetime(
        string='الموعد النهائي للحل',
        readonly=True,
    )

    first_response_at = fields.Datetime(
        string='تاريخ أول استجابة',
        readonly=True,
    )

    sla_response_status = fields.Selection(
        [
            ('in_progress', 'قيد الانتظار'),
            ('successful', 'محقق'),
            ('failed', 'متجاوز'),
        ],
        string='حالة SLA الاستجابة',
        default='in_progress',
        readonly=True,
    )

    sla_resolution_status = fields.Selection(
        [
            ('in_progress', 'قيد الانتظار'),
            ('successful', 'محقق'),
            ('failed', 'متجاوز'),
        ],
        string='حالة SLA الحل',
        default='in_progress',
        readonly=True,
    )

    sla_response_alert_level = fields.Integer(
        string='مستوى تنبيه SLA الاستجابة',
        default=0,
        readonly=True,
    )

    sla_resolution_alert_level = fields.Integer(
        string='مستوى تنبيه SLA الحل',
        default=0,
        readonly=True,
    )

    sla_policy_id = fields.Many2one(
        'support.sla.policy',
        string='سياسة SLA',
        readonly=True,
        copy=False,
    )


    def _apply_sla_policy(self):
        for ticket in self:
            if (
                ticket.status == 'draft'
                or not ticket.category_id
                or not ticket.priority
            ):
                continue

            policy = self.env[
                'support.sla.policy'
            ].sudo().search(
                [
                    (
                        'category_id',
                        '=',
                        ticket.category_id.id
                    ),
                    (
                        'priority',
                        '=',
                        ticket.priority
                    ),
                    (
                        'active',
                        '=',
                        True
                    ),
                ],
                limit=1
            )

            if not policy:
                continue

            start_time = fields.Datetime.to_datetime(
                 ticket.submitted_at
                 or ticket.create_date
                 or fields.Datetime.now()
                 )

            if not start_time.tzinfo:
                start_time = UTC.localize(
                    start_time
                )

            response_deadline = policy.calendar_id.plan_hours(
                policy.response_hours,
                start_time,
                compute_leaves=True,
                
            )
    
            resolution_deadline = policy.calendar_id.plan_hours(
                policy.resolution_hours,
                start_time,
                compute_leaves=True,
            )

            if (
                response_deadline
                and response_deadline.tzinfo
            ):
                response_deadline = response_deadline.replace(
                    tzinfo=None
                )

            if (
                resolution_deadline
                and resolution_deadline.tzinfo
            ):
                resolution_deadline = resolution_deadline.replace(
                    tzinfo=None
                )
            ticket.write({
                'sla_policy_id':
                    policy.id,

                'sla_response_deadline':
                    response_deadline,

                'sla_resolution_deadline':
                    resolution_deadline,

                'sla_response_status':
                    'in_progress',

                'sla_resolution_status':
                    'in_progress',
            })
    def pause_resolution_sla(self, reason):
        self.ensure_one()

        if self.status != 'processing':
            raise ValidationError(
                'يمكن تعليق الطلب فقط أثناء المعالجة.'
            )

        allowed_reasons = {
            'waiting_employee',
            'waiting_approval',
            'waiting_internal',
            'scheduled',
        }

        if reason not in allowed_reasons:
            raise ValidationError(
                'سبب تعليق الطلب غير صحيح.'
            )

        self.write({
            'status': 'on_hold',
            'sla_pause_started_at': fields.Datetime.now(),
            'sla_pause_reason': reason,
            'sla_pause_count': self.sla_pause_count + 1,
        })

        return True


    def resume_resolution_sla(self):
        self.ensure_one()

        if self.status != 'on_hold':
            raise ValidationError(
                'الطلب غير معلق حاليًا.'
            )

        if not self.sla_pause_started_at:
            raise ValidationError(
                'وقت بداية التعليق غير مسجل.'
            )

        resume_time = fields.Datetime.now()

        pause_start = fields.Datetime.to_datetime(
            self.sla_pause_started_at
        )

        pause_end = fields.Datetime.to_datetime(
            resume_time
        )

        if not pause_start.tzinfo:
            pause_start = UTC.localize(
                pause_start
            )

        if not pause_end.tzinfo:
            pause_end = UTC.localize(
                pause_end
            )

        calendar = (
            self.sla_policy_id.calendar_id
            or self.env.company.resource_calendar_id
        )

        paused_hours = calendar.get_work_hours_count(
            pause_start,
            pause_end,
            compute_leaves=True,
        )

        values = {
            'status': 'processing',
            'sla_pause_started_at': False,
            'sla_pause_reason': False,
            'sla_paused_hours':
                self.sla_paused_hours + paused_hours,
        }

        if (
            self.sla_resolution_deadline
            and self.sla_resolution_status == 'in_progress'
            and paused_hours > 0
        ):
            old_deadline = fields.Datetime.to_datetime(
                self.sla_resolution_deadline
            )

            if not old_deadline.tzinfo:
                old_deadline = UTC.localize(
                    old_deadline
                )

            new_deadline = calendar.plan_hours(
                paused_hours,
                old_deadline,
                compute_leaves=True,
            )

            if (
                new_deadline
                and new_deadline.tzinfo
            ):
                new_deadline = new_deadline.replace(
                    tzinfo=None
                )

            values[
                'sla_resolution_deadline'
            ] = new_deadline

        self.write(values)

        return True
    def get_sla_metrics(
        self,
        sla_type='resolution'
    ):

        self.ensure_one()

        if sla_type == 'response':

            start_at = self.submitted_at

            allowed_hours = (
                self.sla_policy_id.response_hours
                if self.sla_policy_id
                else 0.0
            )

            deadline = self.sla_response_deadline

            status = self.sla_response_status

            now = fields.Datetime.now()

        else:

            start_at = self.submitted_at

            allowed_hours = (
                self.sla_policy_id.resolution_hours
                if self.sla_policy_id
                else 0.0
            )

            deadline = self.sla_resolution_deadline

            status = self.sla_resolution_status

            if (
                self.status == 'on_hold'
                and self.sla_pause_started_at
            ):

                now = self.sla_pause_started_at

            else:

                now = fields.Datetime.now()

        if (
            not start_at
            or not allowed_hours
            or not deadline
        ):

            return {
                'percent': 0.0,
                'remaining_hours': 0.0,
                'remaining_seconds': 0,
                'status': status or '',
                'is_working_time': False,
            }

        calendar = (
            self.sla_policy_id.calendar_id
            or self.env.company.resource_calendar_id
        )

        start_at = fields.Datetime.to_datetime(
            start_at
        )

        now = fields.Datetime.to_datetime(
            now
        )

        deadline = fields.Datetime.to_datetime(
            deadline
        )

        if not start_at.tzinfo:
            start_at = UTC.localize(
                start_at
            )

        if not now.tzinfo:
            now = UTC.localize(
                now
            )

        if not deadline.tzinfo:
            deadline = UTC.localize(
                deadline
            )

        used_hours = calendar.get_work_hours_count(
            start_at,
            now,
            compute_leaves=True,
        )

        remaining_hours = calendar.get_work_hours_count(
            now,
            deadline,
            compute_leaves=True,
        )

        check_end = now + relativedelta(
            minutes=1
        )

        is_working_time = (
            calendar.get_work_hours_count(
                now,
                check_end,
                compute_leaves=True,
            ) > 0
        )

        percent = (
            used_hours
            / allowed_hours
        ) * 100

        return {
            'percent': round(
                max(
                    0.0,
                    percent
                ),
                1
            ),

            'remaining_hours': round(
                max(
                    0.0,
                    remaining_hours
                ),
    2
),

'remaining_seconds': max(
    0,
    int(remaining_hours * 3600)
),

'status': status or '',
            'is_working_time':
                is_working_time,
        }
    
    def _get_sla_alert_level(self, percent):
        if percent >= 100:
            return 100

        if percent >= 90:
            return 90

        if percent >= 75:
            return 75

        return 0

    def _send_sla_alert(
        self,
        sla_type,
        level
    ):
        self.ensure_one()

        if self.assignee_id:
            partners = self.assignee_id.partner_id

        elif level == 100:
            support_group = self.env.ref(
                'website.group_support_manager',
                raise_if_not_found=False
            )

            partners = (
                support_group.users.mapped('partner_id')
                if support_group
                else self.env['res.partner']
            )

        else:
            return False

        if not partners:
            return False

        if sla_type == 'response':  
            if level == 75:
                subject = (
                    'تنبيه SLA الاستجابة'
                )
                body = (
                    f'اقترب موعد الاستجابة '
                    f'للطلب {self.ticket_number}.'
                )

            elif level == 90:
                subject = (
                    'تحذير SLA الاستجابة'
                )
                body = (
                    f'تبقى وقت محدود قبل '
                    f'تجاوز SLA الاستجابة '
                    f'للطلب {self.ticket_number}.'
                )

            else:
                subject = (
                    'تجاوز SLA الاستجابة'
                )
                body = (
                    f'تم تجاوز SLA الاستجابة '
                    f'للطلب {self.ticket_number}.'
                )

        else:

            if level == 75:
                subject = (
                    'تنبيه SLA الحل'
                )
                body = (
                    f'اقترب موعد الحل '
                    f'للطلب {self.ticket_number}.'
                )

            elif level == 90:
                subject = (
                    'تحذير SLA الحل'
                )
                body = (
                    f'تبقى وقت محدود قبل '
                    f'تجاوز SLA الحل '
                    f'للطلب {self.ticket_number}.'
                )

            else:
                subject = (
                    'تجاوز SLA الحل'
                )
                body = (
                    f'تم تجاوز SLA الحل '
                    f'للطلب {self.ticket_number}.'
                )
        message = self.message_post(
            subject=subject,
            body=body,
            partner_ids=partners.ids,
            message_type='notification',
        )

        notifications = self.env[
            'mail.notification'
        ].sudo().search(
            [
                (
                    'mail_message_id',
                    '=',
                    message.id
                ),
                (
                    'res_partner_id',
                    'in',
                    partners.ids
                ),
            ]
        )

        if notifications:
            notifications.write({
                'is_read': False,
            })

        return True
    @api.model
    def _cron_update_sla_statuses(self):

        now = fields.Datetime.now()

        tickets = self.search([
            ('status', '!=', 'draft'),
            ('sla_policy_id', '!=', False),
        ])

        for ticket in tickets:

            # -------------------------
            # SLA الاستجابة
            # -------------------------
            if (
                ticket.sla_response_status
                == 'in_progress'
                and not ticket.first_response_at
            ):

                response_metrics = (
                    ticket.get_sla_metrics(
                        'response'
                    )
                )

                response_level = (
                    ticket._get_sla_alert_level(
                        response_metrics[
                            'percent'
                        ]
                    )
                )

                if (
                    response_level
                    > ticket.sla_response_alert_level
                ):
                    sent = ticket._send_sla_alert(
                        'response',
                        response_level
                    )
                    if sent:
                        ticket.write({
                        'sla_response_alert_level':
                            response_level,
                    })

                if (
                    ticket.sla_response_deadline
                    and now
                    > ticket.sla_response_deadline
                ):

                    sent = False

                    if ticket.sla_response_alert_level < 100:
                        sent = ticket._send_sla_alert(
                            'response',
                            100
                        )

                    values = {
                        'sla_response_status':
                            'failed',
                    }

                    if sent:
                        values[
                            'sla_response_alert_level'
                        ] = 100

                    ticket.write(values)
            # SLA الحل

            if (
                ticket.sla_resolution_status
                == 'in_progress'
                and ticket.status
                in ['new', 'processing']
            ):

                resolution_metrics = (
                    ticket.get_sla_metrics(
                        'resolution'
                    )
                )

                resolution_level = (
                    ticket._get_sla_alert_level(
                        resolution_metrics[
                            'percent'
                        ]
                    )
                )

                if (
                    resolution_level
                    > ticket.sla_resolution_alert_level
                ):
                    sent = ticket._send_sla_alert(
                        'resolution',
                        resolution_level
                    )

                    if sent:
                        ticket.write({
                            'sla_resolution_alert_level':
                                resolution_level,
                        })
                if (
                    ticket.sla_resolution_deadline
                    and now
                    > ticket.sla_resolution_deadline
                ):

                    sent = False

                    if ticket.sla_resolution_alert_level < 100:
                        sent = ticket._send_sla_alert(
                            'resolution',
                            100
                        )

                    values = {
                        'sla_resolution_status':
                            'failed',
                    }

                    if sent:
                        values[
                            'sla_resolution_alert_level'
                        ] = 100

                    ticket.write(values)

        return True

    @api.constrains(
        'status',
        'ticket_number',
        'title',
        'description',
        'category_id',
        'priority'
    )
    def _check_submitted_ticket_fields(self):

        for ticket in self:

            if ticket.status == 'draft':
                continue

            if not ticket.ticket_number:
                raise ValidationError(
                    'رقم الطلب مطلوب بعد الإرسال.'
                )

            if not ticket.title:
                raise ValidationError(
                    'موضوع الطلب مطلوب.'
                )

            if not ticket.description:
                raise ValidationError(
                    'وصف المشكلة مطلوب.'
                )

            if not ticket.category_id:
                raise ValidationError(
                    'تصنيف الطلب مطلوب.'
                )

            if not ticket.priority:
                raise ValidationError(
                    'الأولوية مطلوبة.'
                )


    @api.constrains(
        'category_id',
        'priority'
    )
    def _check_inquiry_priority(self):

        for ticket in self:

            if (
                ticket.category_id
                and ticket.category_id.name == 'استفسار'
                and ticket.priority == 'high'
            ):

                raise ValidationError(
                    'لا يمكن اختيار أولوية عالية لطلب من نوع استفسار.'
                )


    _sql_constraints = [
        (
            'support_ticket_number_unique',
            'unique(ticket_number)',
            'رقم الطلب يجب أن يكون فريدًا.',
        )
    ]    